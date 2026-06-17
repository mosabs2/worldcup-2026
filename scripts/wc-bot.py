#!/usr/bin/env python3
"""Interactive World Cup league bot (@MoSabsWCBot).

A participant DMs the bot their name and gets back their league standing: rank and
points so far, group-winner hits, their finalists/champion picks, and their Golden
Boot pick vs the current leader. Replies in Arabic when the message is in Arabic,
otherwise English. Data is the live src/data.js pulled from GitHub (cached briefly).

Runs on the always-on Mac mini as a self-healing long-poll loop: cron launches it
every minute, an flock ensures only one instance runs, and the loop long-polls
getUpdates(timeout=30). If it dies, cron restarts it within a minute.

Token from ~/.claude/telegram-bot-token (0600). Stdlib only.
  Run the loop:   python3 wc-bot.py
  Test a reply:   python3 wc-bot.py --test "Abdullah Khaled"
"""
import json, os, sys, re, time, fcntl, urllib.request, urllib.parse, urllib.error

TOKEN_FILE = os.path.expanduser("~/.claude/telegram-bot-token")
OFFSET_FILE = os.path.expanduser("~/.claude/jobs/wc-bot-offset")
LOCK_FILE = os.path.expanduser("~/.claude/jobs/wc-bot.lock")
LOGDIR = os.path.expanduser("~/.claude/jobs/logs")
DATA_URL = "https://raw.githubusercontent.com/mosabs2/worldcup-2026/main/src/data.js"
SITE = "https://mosabs2.github.io/worldcup-2026/#mine"
import datetime as _dt

def log(m):
    os.makedirs(LOGDIR, exist_ok=True)
    with open(os.path.join(LOGDIR, "wc-bot-%s.log" % _dt.date.today().isoformat()), "a") as f:
        f.write(time.strftime("%H:%M:%S") + " " + m + "\n")

def is_arabic(s):
    return bool(re.search(r"[؀-ۿ]", s or ""))

# ---- data ----------------------------------------------------------------
_cache = {"data": None, "at": 0}
def get_data(max_age=180):
    if _cache["data"] and time.time() - _cache["at"] < max_age:
        return _cache["data"]
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": "wc-bot/1.0"})
    raw = urllib.request.urlopen(req, timeout=20).read().decode()
    m = re.search(r"const WC_DATA = (\{.*?\});\nif", raw, re.S)
    d = json.loads(m.group(1))
    _cache["data"], _cache["at"] = d, time.time()
    return d

def teams_index(d):
    return {t["code"]: t for t in d["teams"]}

def group_winners(d):
    """Resolved winner per fully-completed group, by pts -> GD -> GF (provisional)."""
    out = {}
    groups = sorted({t["group"] for t in d["teams"]})
    for g in groups:
        codes = [t["code"] for t in d["teams"] if t["group"] == g]
        tbl = {c: {"P": 0, "pts": 0, "gf": 0, "ga": 0} for c in codes}
        for mt in d["matches"]:
            if mt.get("group") != g:
                continue
            sc = mt.get("score")
            if mt.get("status") == "completed" and sc and mt["team1"] in tbl and mt["team2"] in tbl:
                a, b, ga, gb = mt["team1"], mt["team2"], sc["team1"], sc["team2"]
                tbl[a]["P"] += 1; tbl[b]["P"] += 1
                tbl[a]["gf"] += ga; tbl[a]["ga"] += gb; tbl[b]["gf"] += gb; tbl[b]["ga"] += ga
                if ga > gb: tbl[a]["pts"] += 3
                elif gb > ga: tbl[b]["pts"] += 3
                else: tbl[a]["pts"] += 1; tbl[b]["pts"] += 1
        if all(tbl[c]["P"] >= 3 for c in codes):  # group complete
            order = sorted(codes, key=lambda c: (-tbl[c]["pts"], -(tbl[c]["gf"] - tbl[c]["ga"]), -tbl[c]["gf"], c))
            out[g] = order[0]
    return out

def standings(d):
    """Points so far per entry (resolved group winners only, pre-knockout), ranked."""
    sc = d["league"]["scoring"]; gw = group_winners(d)
    rows = []
    for e in d["league"]["entries"]:
        pts = sum(sc["groupWinner"] for g, win in gw.items() if (e.get("w") or {}).get(g) == win)
        rows.append({"e": e, "pts": pts})
    rows.sort(key=lambda r: -r["pts"])
    # rank with ties sharing position; exhibition entries unranked
    rank, last, n = 0, None, 0
    for r in rows:
        if r["e"].get("exhibition"):
            r["rank"] = "★"; continue
        n += 1
        if r["pts"] != last:
            rank = n; last = r["pts"]
        r["rank"] = rank
    total = sum(1 for r in rows if not r["e"].get("exhibition"))
    return rows, gw, total

def find_entries(query, d):
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []
    names = {e["n"] for e in d["league"]["entries"]}
    hits = [n for n in names if q == n.lower()]
    if not hits:
        hits = [n for n in names if q in n.lower() or n.lower() in q]
    return sorted(set(hits))

# ---- reply text ----------------------------------------------------------
def build_reply(text, d=None):
    if d is None:
        d = get_data()
    t = (text or "").strip()
    ar = is_arabic(t)
    T = teams_index(d)
    fl = lambda c: (T.get(c) or {}).get("flag", "")
    nm = lambda c: (T.get(c) or {}).get("name", c)

    if t in ("/start", "start", "/help", "help", "بدء", "/بدء", "مساعدة"):
        if ar:
            return ("⚽ أهلاً بك في بوت دوري كأس العالم!\n\n"
                    "أرسل اسمك كما هو مسجّل في الدوري (بالإنجليزية) وسأعطيك ترتيبك ونقاطك واختياراتك.\n"
                    "مثال: اكتب اسمك فقط.\n\n"
                    "التنبيهات المباشرة للأهداف والمباريات في القناة: https://t.me/MoSabsWC26")
        return ("⚽ Welcome to the World Cup league bot!\n\n"
                "Send me your name as it appears in the league and I'll give you your rank, points and picks.\n"
                "Just type your name.\n\n"
                "Live goal & kick-off alerts are in the channel: https://t.me/MoSabsWC26")

    matches = find_entries(t, d)
    if not matches:
        if ar:
            return ("لم أجد هذا الاسم في الدوري. أرسل اسمك كما هو مسجّل تماماً (بالإنجليزية).\n"
                    "للمساعدة اكتب /help")
        return ("I couldn't find that name in the league. Send your name exactly as it's registered.\n"
                "Type /help for help.")
    if len(matches) > 1:
        lst = "\n".join("• " + n for n in matches[:12])
        if ar:
            return "وجدت أكثر من اسم. أيّهم أنت؟\n" + lst
        return "I found more than one match — which are you?\n" + lst

    name = matches[0]
    rows, gw, total = standings(d)
    me = next((r for r in rows if r["e"]["n"] == name), None)
    e = me["e"]
    resolved = len(gw)
    gw_hits = sum(1 for g, win in gw.items() if (e.get("w") or {}).get(g) == win)
    champ = e.get("c"); fins = [c for c in (e.get("f") or []) if T.get(c)]
    pe = next((p for p in d["league"].get("props", []) if (p.get("n") or "").lower() == name.lower()), None)
    pl = d.get("propsLive") or {}
    lead = (pl.get("topScorers") or [None])[0]

    if ar:
        lines = ["🏆 " + name + " — دوري كأس العالم",
                 "الترتيب: #%s من %d  ·  %d نقطة حتى الآن" % (me["rank"], total, me["pts"]),
                 "أبطال المجموعات: %d صحيحة من %d محسومة" % (gw_hits, resolved),
                 "بطلك: %s %s" % (fl(champ), nm(champ)) if champ else "بطلك: —",
                 "نهائيك: " + ("، ".join(fl(c) + " " + nm(c) for c in fins) if fins else "—")]
        if pe:
            gbtxt = pe["gb"]["p"]
            if lead:
                gbtxt += "  (المتصدّر الآن: %s بـ %d)" % (lead["player"], lead["goals"])
            lines.append("هدّافك المختار: " + gbtxt)
        lines.append("ترتيبك المباشر الكامل: " + SITE)
        return "\n".join(lines)

    lines = ["🏆 " + name + " — your World Cup league",
             "Rank: #%s of %d  ·  %d pts so far" % (me["rank"], total, me["pts"]),
             "Group winners right: %d of %d resolved" % (gw_hits, resolved),
             "Your champion: %s %s" % (fl(champ), nm(champ)) if champ else "Your champion: —",
             "Your finalists: " + (", ".join(fl(c) + " " + nm(c) for c in fins) if fins else "—")]
    if pe:
        gbtxt = pe["gb"]["p"]
        if lead:
            gbtxt += "  (leader now: %s on %d)" % (lead["player"], lead["goals"])
        lines.append("Golden Boot pick: " + gbtxt)
    lines.append("Your full live standing: " + SITE)
    return "\n".join(lines)

# ---- telegram loop -------------------------------------------------------
def api(token, method, params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen("https://api.telegram.org/bot%s/%s" % (token, method), data=data, timeout=40) as r:
        return json.load(r)

def run():
    # One short polling cycle, designed to be launched by cron every minute. It
    # long-polls ~50s for any waiting messages, answers them, and exits — so it can
    # never get stuck or crash-loop; cron simply runs it again next minute. flock
    # stops two cycles overlapping (which Telegram would reject with a 409).
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # previous cycle still polling
    if not os.path.exists(TOKEN_FILE):
        return
    token = open(TOKEN_FILE).read().strip()
    try:
        offset = int(open(OFFSET_FILE).read().strip())
    except Exception:
        offset = 0
    try:
        res = api(token, "getUpdates", {"offset": offset, "timeout": 50})
        handled = 0
        for u in res.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message")
            if not msg or "text" not in msg or msg.get("chat", {}).get("type") != "private":
                continue
            try:
                reply = build_reply(msg["text"])
            except Exception as ex:
                reply = "Sorry, something went wrong — try again in a moment."
                log("reply err: %s" % ex)
            api(token, "sendMessage", {"chat_id": msg["chat"]["id"], "text": reply, "disable_web_page_preview": "true"})
            handled += 1
        open(OFFSET_FILE, "w").write(str(offset))
        if handled:
            log("handled %d message(s)" % handled)
    except urllib.error.HTTPError as e:
        log("http %s %s" % (e.code, e.read().decode()[:120]))
    except Exception as ex:
        log("cycle err %s" % ex)

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        print(build_reply(sys.argv[2]))
    else:
        run()
