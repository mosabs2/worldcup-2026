#!/usr/bin/env python3
"""Walk-forward calibration backtest: the current Elo model vs the market's
closing-odds implied probabilities, scored on the 12 played 2026 matches.

For each completed group game in date order, the model's PRE-match probs are
computed from ratings updated only by earlier games (no look-ahead), exactly
mirroring engine.js predict()/liveRatings(). Market probs come from the
vig-removed closing 1X2 in .cache/statsapi.json. Both are scored by multiclass
log-loss and Brier against the actual W/D/L outcome (lower = sharper).
"""
import json, math, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")
CACHE = os.path.join(ROOT, ".cache", "statsapi.json")

# ---- engine.js constants (kept in sync) ----
HOST_BONUS, ELO_K, LOGISTIC_DIV = 55, 40, 420
HOSTS = {"MEX", "USA", "CAN"}
HOST_COUNTRY = {"MEX": "Mexico", "USA": "United States", "CAN": "Canada"}

def margin_mult(gd):
    if gd <= 1: return 1
    if gd == 2: return 1.5
    return (11 + gd) / 8

raw = open(DATA).read()
data = json.loads(re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S).group(1))
venue_country = {v["id"]: v["country"] for v in data["venues"]}
base = {t["code"]: t["baseRating"] for t in data["teams"]}

def host_edge(code, venue):
    if code in HOSTS and venue and venue_country.get(venue) == HOST_COUNTRY[code]:
        return HOST_BONUS
    return 0

def predict(ra, rb):
    diff = ra - rb
    p_a = 1 / (1 + 10 ** (-diff / LOGISTIC_DIV))
    draw = max(0.17, min(0.30, 0.27 - abs(diff) / 2600))
    return (1 - draw) * p_a, draw, (1 - draw) * (1 - p_a)   # (p1, draw, p2) team1 POV

cache = json.load(open(CACHE))["matches"]
# index cached odds by frozenset of the two codes
odds_by_pair = {}
for r in cache.values():
    if r.get("odds_prob") and r.get("home") and r.get("away"):
        odds_by_pair[frozenset((r["home"], r["away"]))] = r

played = sorted([m for m in data["matches"] if m["status"] == "completed" and m.get("score")],
                key=lambda m: m["dateET"])

ratings = dict(base)
LL = {"model": 0.0, "market": 0.0}; BR = {"model": 0.0, "market": 0.0}
n_market = 0
rows = []
EPS = 1e-9
for m in played:
    t1, t2, v = m["team1"], m["team2"], m.get("venueId")
    ra = ratings[t1] + host_edge(t1, v)
    rb = ratings[t2] + host_edge(t2, v)
    pm = predict(ra, rb)                                   # model pre-match (p1,draw,p2)
    g1, g2 = m["score"]["team1"], m["score"]["team2"]
    outcome = 0 if g1 > g2 else 2 if g2 > g1 else 1        # index into (1,X,2)
    actual = [1 if i == outcome else 0 for i in range(3)]

    # market, oriented to team1 POV
    rec = odds_by_pair.get(frozenset((t1, t2)))
    mk = None
    if rec:
        op = rec["odds_prob"]
        mk = (op["h"], op["x"], op["a"]) if rec["home"] == t1 else (op["a"], op["x"], op["h"])

    def score(probs):
        p = [min(1 - EPS, max(EPS, x)) for x in probs]
        ll = -math.log(p[outcome])
        br = sum((p[i] - actual[i]) ** 2 for i in range(3))
        return ll, br
    ll_m, br_m = score(pm); LL["model"] += ll_m; BR["model"] += br_m
    if mk:
        ll_k, br_k = score(mk); LL["market"] += ll_k; BR["market"] += br_k; n_market += 1
    rows.append((m["dateET"][:10], t1, g1, g2, t2, pm, mk, ["1","X","2"][outcome], rec["odds_prob"].get("book") if rec else None))

    # update ratings (post-match), mirroring liveRatings
    w = 1 if g1 > g2 else 0 if g1 < g2 else 0.5
    exp = 1 / (1 + 10 ** (-((ratings[t1] + host_edge(t1, v)) - (ratings[t2] + host_edge(t2, v))) / LOGISTIC_DIV))
    ch = ELO_K * margin_mult(abs(g1 - g2)) * (w - exp)
    ratings[t1] += ch; ratings[t2] -= ch

n = len(played)
print(f"played games scored: {n} | market odds matched: {n_market}/{n}\n")
print(f"{'date':10} {'fixture':22} {'res':3} {'model 1/X/2':18} {'market 1/X/2':18} book")
for d, t1, g1, g2, t2, pm, mk, res, book in rows:
    fx = f"{t1} {g1}-{g2} {t2}"
    pms = f"{pm[0]:.0%}/{pm[1]:.0%}/{pm[2]:.0%}"
    mks = f"{mk[0]:.0%}/{mk[1]:.0%}/{mk[2]:.0%}" if mk else "—"
    print(f"{d:10} {fx:22} {res:3} {pms:18} {mks:18} {book or ''}")

print("\n=== calibration (lower is sharper) ===")
print(f"{'metric':10} {'model':>10} {'market':>10}  {'market edge':>12}")
mll, kll = LL['model']/n, LL['market']/max(n_market,1)
mbr, kbr = BR['model']/n, BR['market']/max(n_market,1)
print(f"{'log-loss':10} {mll:10.4f} {kll:10.4f}  {(mll-kll)/mll*100:>11.1f}%")
print(f"{'brier':10} {mbr:10.4f} {kbr:10.4f}  {(mbr-kbr)/mbr*100:>11.1f}%")
print("\n(market edge = how much lower the market's error is, vs the model. "
      "Positive => market sharper. Note n=12 is small; treat as directional.)")
