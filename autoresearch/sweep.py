#!/usr/bin/env python3
"""sweep.py — the sober alternative to loop.sh.

For eight numeric constants, an LLM-in-the-loop is theatre: a deterministic
coordinate search finds the same or better optimum, for free, reproducibly, in
under a second. This does exactly that against the SAME locked scorer
(score.py's model + drift penalty), so it honours the same anti-overfit rules.

It coordinate-descends each tunable constant over a local grid, keeps a step only
if SCORE drops, and repeats until no constant improves. Then it reruns the full
diagnostic so you can read ALL_LL vs TAIL_LL and decide whether the gain is real.

Usage:  python3 autoresearch/sweep.py            # search, print result, DON'T write
        python3 autoresearch/sweep.py --write     # also write best to params.json
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = os.path.join(HERE, "params.json")
SCORE = os.path.join(HERE, "score.py")

# import the scorer's model directly for speed (no subprocess per eval)
sys.path.insert(0, HERE)
import score as S  # noqa: E402

import re
import math


def load_data():
    raw = open(S.DATA).read()
    data = json.loads(re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S).group(1))
    venue_country = {v["id"]: v["country"] for v in data["venues"]}
    base = {t["code"]: t["baseRating"] for t in data["teams"]}
    played = sorted([m for m in data["matches"] if m["status"] == "completed" and m.get("score")],
                    key=lambda m: m["dateET"])
    return data, venue_country, base, played


def evaluate(P, base, venue_country, played):
    """Replays the model; returns (score, all_ll, tail_ll) or inf if out of bounds."""
    for k in S.SEED:
        lo, hi = S.BOUNDS[k]
        if not (lo <= P[k] <= hi):
            return math.inf, math.inf, math.inf
    if P["DRAW_FLOOR"] >= P["DRAW_CEIL"]:
        return math.inf, math.inf, math.inf

    def host_edge(code, venue):
        if code in S.HOSTS and venue and venue_country.get(venue) == S.HOST_COUNTRY[code]:
            return P["HOST_BONUS"]
        return 0.0

    def predict(ra, rb):
        diff = ra - rb
        p_a = 1 / (1 + 10 ** (-diff / P["LOGISTIC_DIV"]))
        draw = max(P["DRAW_FLOOR"], min(P["DRAW_CEIL"], P["DRAW_BASE"] - abs(diff) / P["DRAW_DIV"]))
        return [(1 - draw) * p_a, draw, (1 - draw) * (1 - p_a)]

    ratings = dict(base)
    lls = []
    for m in played:
        t1, t2, v = m["team1"], m["team2"], m.get("venueId")
        ra = ratings[t1] + host_edge(t1, v)
        rb = ratings[t2] + host_edge(t2, v)
        probs = predict(ra, rb)
        g1, g2 = m["score"]["team1"], m["score"]["team2"]
        outcome = 0 if g1 > g2 else 2 if g2 > g1 else 1
        p = min(1 - S.EPS, max(S.EPS, probs[outcome]))
        lls.append(-math.log(p))
        w = 1.0 if g1 > g2 else 0.0 if g1 < g2 else 0.5
        exp = 1 / (1 + 10 ** (-((ratings[t1] + host_edge(t1, v)) - (ratings[t2] + host_edge(t2, v))) / P["LOGISTIC_DIV"]))
        ch = P["ELO_K"] * S.margin_mult(S.effective_gd(g1, g2, m.get("xg"), P["XG_TEMPER"])) * (w - exp)
        ratings[t1] += ch
        ratings[t2] -= ch
    n = len(lls)
    all_ll = sum(lls) / n
    tail = lls[max(0, n - max(3, n // 3)):]
    tail_ll = sum(tail) / len(tail)
    drift = sum(((P[k] - S.SEED[k]) / S.SEED[k]) ** 2 for k in S.SEED)
    return all_ll + S.DRIFT_LAMBDA * drift, all_ll, tail_ll


# coordinate steps per constant (absolute units)
STEPS = {
    "LOGISTIC_DIV": [10, 25], "DRAW_BASE": [0.005, 0.015], "DRAW_DIV": [100, 300],
    "ELO_K": [2, 5], "HOST_BONUS": [5, 10], "XG_TEMPER": [0.05, 0.1],
    "DRAW_FLOOR": [0.01], "DRAW_CEIL": [0.01],
}


def main():
    data, vc, base, played = load_data()
    P = {k: float(S.SEED[k]) for k in S.SEED}
    best, ball, btail = evaluate(P, base, vc, played)
    seed_score = best
    improved = True
    rounds = 0
    while improved and rounds < 20:
        improved = False
        rounds += 1
        for k in STEPS:
            for step in STEPS[k]:
                for d in (+step, -step):
                    trial = dict(P)
                    trial[k] = round(P[k] + d, 6)
                    s, a, t = evaluate(trial, base, vc, played)
                    if s < best - 1e-9:
                        P, best, ball, btail = trial, s, a, t
                        improved = True
    moved = {k: (round(S.SEED[k], 4), round(P[k], 4)) for k in S.SEED if abs(P[k] - S.SEED[k]) > 1e-9}
    print(f"seed  SCORE={seed_score:.5f}")
    print(f"best  SCORE={best:.5f}  ALL_LL={ball:.5f}  TAIL_LL={btail:.5f}")
    print(f"gain  {seed_score - best:+.5f}  ({(seed_score - best) / seed_score * 100:+.1f}%)")
    print("moved constants (seed -> best):")
    for k, (a, b) in moved.items():
        print(f"  {k:13} {a} -> {b}")
    if not moved:
        print("  (none — seed values already optimal under the penalty)")
    if "--write" in sys.argv:
        cur = json.load(open(PARAMS))
        for k in S.SEED:
            cur[k] = P[k]
        json.dump(cur, open(PARAMS, "w"), indent=2)
        print(f"\nwrote best params to {PARAMS}")
    else:
        print("\n(dry run — pass --write to save to params.json)")


if __name__ == "__main__":
    main()
