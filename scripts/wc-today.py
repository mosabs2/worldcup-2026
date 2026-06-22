#!/usr/bin/env python3
"""Daily "today's matches" announcement, posted to the family Telegram channel.

Runs once a day at 16:00 Kuwait (cron on the mini: `0 14 * * *` London local =
13:00 UTC = 16:00 +03), a few hours before the evening's first kick-off. Reads the
free ESPN World Cup scoreboard (same feed the site and wc-notify use), lists the
night's matches with kick-off times converted to Kuwait time (+03), and posts one
message to @MoSabsWC26. On a rest day it posts a single "no matches" line.

The flyer stays a separate manual step (Mohammed generates it in ChatGPT and posts
the image himself); this job is the reliable text backbone only.

Token from ~/.claude/telegram-bot-token (0600). Stdlib only.
Deployed copy: ~/.claude/jobs/wc-today.py. Self-terminates after 2026-07-20.

Usage: wc-today.py [--dry-run]   (--dry-run prints the message, posts nothing)
"""
import json, os, sys, urllib.request, urllib.parse, urllib.error, datetime as dt

CHAT = "@MoSabsWC26"
TOKEN_FILE = os.path.expanduser("~/.claude/telegram-bot-token")
SENT_FILE = os.path.expanduser("~/.claude/jobs/wc-today-last.txt")   # last Kuwait date posted
LOGDIR = os.path.expanduser("~/.claude/jobs/logs")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=%s"
KWT = dt.timezone(dt.timedelta(hours=3))            # Kuwait is UTC+3, no DST
LAST_DAY = "2026-07-20"                              # tournament self-terminate

DRY = "--dry-run" in sys.argv


def log(msg):
    try:
        os.makedirs(LOGDIR, exist_ok=True)
        with open(os.path.join(LOGDIR, "wc-today-%s.log" % dt.date.today().isoformat()), "a") as f:
            f.write("%s %s\n" % (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), msg))
    except Exception:
        pass


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wc-today/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def group_label(ev):
    """Best-effort group/round label, e.g. 'Group E'. Degrades to '' if absent."""
    try:
        notes = ev["competitions"][0].get("notes") or []
        if notes:
            head = (notes[0].get("headline") or "").strip()
            if head:
                # ESPN headlines look like "Group E - FIFA World Cup"; keep the lead.
                return head.split(" - ")[0].strip()
    except Exception:
        pass
    return ""


def matches_window():
    """Tonight's slate, by Kuwait calendar day, independent of the exact fire time:
    a match is included if its Kuwait kick-off falls on today (Kuwait), or in the
    early hours of tomorrow (before 09:00 +03) since the North-American evening slate
    runs ~19:00 today to ~06:00 tomorrow Kuwait. Fetches today's and tomorrow's ESPN
    dates so late matches crossing midnight UTC are covered."""
    now = dt.datetime.now(dt.timezone.utc)
    today_kwt = now.astimezone(KWT).date()
    tomorrow_kwt = today_kwt + dt.timedelta(days=1)
    seen, out = set(), []
    for d in (now, now + dt.timedelta(days=1)):
        try:
            events = fetch(ESPN % d.strftime("%Y%m%d")).get("events", [])
        except Exception as e:
            log("fetch failed for %s: %s" % (d.date(), e))
            continue
        for ev in events:
            eid = ev.get("id")
            if eid in seen:
                continue
            try:
                ko = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
                kd = ko.astimezone(KWT)
                if kd.date() == today_kwt or (kd.date() == tomorrow_kwt and kd.hour < 9):
                    comp = ev["competitions"][0]["competitors"]
                    home = next((c["team"]["displayName"] for c in comp if c.get("homeAway") == "home"), "?")
                    away = next((c["team"]["displayName"] for c in comp if c.get("homeAway") == "away"), "?")
                    seen.add(eid)
                    out.append((ko, group_label(ev), home, away))
            except Exception as e:               # one malformed event must not drop the whole slate
                log("skip event %s: %s" % (eid, e))
                continue
    out.sort(key=lambda r: r[0])
    return out, now


def build_message():
    # returns (message, had_matches). had_matches=False covers BOTH a genuine rest day
    # and a total feed failure, so the caller can decide not to "lock in" an empty slate.
    rows, now = matches_window()
    today_kwt = now.astimezone(KWT).date()
    if not rows:
        return "⚽ No World Cup matches today. Back tomorrow.", False
    lines = ["⚽ Today's World Cup matches — times in Kuwait (+03)", ""]
    for ko, grp, home, away in rows:
        k = ko.astimezone(KWT)
        t = k.strftime("%H:%M")
        if k.date() != today_kwt:                   # rolled past midnight Kuwait
            t += " (%s)" % k.strftime("%a")
        g = "%s: " % grp if grp else ""
        lines.append(" %s  %s%s vs %s" % (t, g, home, away))
    lines += ["", "Live goals & kick-offs drop in the channel as they happen."]
    return "\n".join(lines), True


def post(text):
    token = open(TOKEN_FILE).read().strip()
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % token, data=data, timeout=20) as r:
        return json.load(r)


def main():
    if dt.date.today().isoformat() > LAST_DAY:
        return
    # Idempotency: post at most once per Kuwait calendar day. A cron double-fire,
    # catch-up run, or manual invocation on the same day is a no-op rather than a
    # duplicate channel post. (--dry-run is exempt: it prints and never posts.)
    today_kwt = dt.datetime.now(dt.timezone.utc).astimezone(KWT).date().isoformat()
    if not DRY:
        try:
            if os.path.exists(SENT_FILE) and open(SENT_FILE).read().strip() == today_kwt:
                log("already posted for %s; skipping" % today_kwt)
                return
        except Exception:
            pass
    msg, had_matches = build_message()
    if DRY:
        print(msg)
        return
    try:
        j = post(msg)
        log("posted ok=%s had_matches=%s" % (j.get("ok"), had_matches))
        # Only lock in the day's post when a real slate went out. A "no matches" line
        # caused by a transient total feed failure is then still correctable by a rerun
        # (cron is once/day, so a genuine rest day won't double-post anyway).
        if had_matches:
            try:
                with open(SENT_FILE, "w") as f:
                    f.write(today_kwt)
            except Exception:
                pass
    except Exception as e:
        log("post failed: %s" % e)
        sys.exit(1)


if __name__ == "__main__":
    main()
