#!/usr/bin/env python3
"""THE SCORING FILE (AI-LOCKED).

Karpathy's auto-research pattern needs an objective scorer the agent cannot
touch, or it games the metric instead of improving the model. This file is that
scorer. The loop driver (loop.sh) treats it as read-only: the agent may edit
params.json and ONLY params.json.

What it does: loads the 2026 World Cup matches that have actually been played,
replays the engine.js model end to end (base ratings -> live Elo updates ->
logistic 1X2) using the constants from params.json, and scores the model's
PRE-match probabilities against the real W/D/L outcomes by multiclass log-loss
(lower = sharper). No look-ahead: each game is scored on ratings updated only by
earlier games, exactly mirroring engine.js liveRatings()/predict().

The headline number is deliberately NOT raw in-sample log-loss, because n is
tiny (14 games as of mid-June 2026). Two guards are built in:

  1. DRIFT PENALTY. A small quadratic penalty on how far each constant has moved
     from its reasoned seed value. With 14 points and 8 knobs, most apparent
     gains are noise; the penalty makes the loop earn a change by beating the
     prior, not just fitting the sample. lambda is fixed here and the agent
     cannot raise it.

  2. TAIL DIAGNOSTIC. Mean log-loss on the last third of games is printed
     separately. If the loop drives ALL_LL down while TAIL_LL goes up, that is
     the classic overfit signature -- read it at the promotion gate (README).

Output contract: the last line is `SCORE=<float>` (lower is better). loop.sh
parses that line and nothing else.
"""
import json
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")
PARAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.json")

# Reasoned seed priors (the current engine.js values). The drift penalty pulls
# toward these; they are NOT read from params.json so the agent cannot move the
# anchor. Keep in sync by hand if you ever re-baseline engine.js.
SEED = {
    "ELO_K": 40.0, "LOGISTIC_DIV": 420.0, "HOST_BONUS": 55.0, "XG_TEMPER": 0.6,
    "DRAW_BASE": 0.27, "DRAW_DIV": 2600.0, "DRAW_FLOOR": 0.17, "DRAW_CEIL": 0.30,
}
# Hard sanity bounds. A proposal outside these is rejected (SCORE=inf) before it
# can poison the loop. Stops the agent wandering into degenerate regions.
BOUNDS = {
    "ELO_K": (10, 80), "LOGISTIC_DIV": (250, 700), "HOST_BONUS": (0, 120),
    "XG_TEMPER": (0.0, 1.0), "DRAW_BASE": (0.18, 0.34), "DRAW_DIV": (1500, 5000),
    "DRAW_FLOOR": (0.10, 0.22), "DRAW_CEIL": (0.24, 0.36),
}
DRIFT_LAMBDA = 0.015   # fixed. weight of the regularisation penalty.
EPS = 1e-9

HOSTS = {"MEX", "USA", "CAN"}
HOST_COUNTRY = {"MEX": "Mexico", "USA": "United States", "CAN": "Canada"}


def margin_mult(gd):
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8.0


def effective_gd(g1, g2, xg, temper):
    actual = abs(g1 - g2)
    if not xg or xg.get("team1") is None or xg.get("team2") is None:
        return actual
    xgd = abs(xg["team1"] - xg["team2"])
    return max(1, round((1 - temper) * actual + temper * xgd))


def load_params():
    p = json.load(open(PARAMS))
    out = {}
    for k in SEED:
        if k not in p:
            raise SystemExit(f"params.json missing key: {k}")
        out[k] = float(p[k])
        lo, hi = BOUNDS[k]
        if not (lo <= out[k] <= hi):
            print(f"[reject] {k}={out[k]} outside bound [{lo},{hi}]")
            print("SCORE=inf")
            raise SystemExit(0)
    if out["DRAW_FLOOR"] >= out["DRAW_CEIL"]:
        print("[reject] DRAW_FLOOR >= DRAW_CEIL")
        print("SCORE=inf")
        raise SystemExit(0)
    return out


def main():
    raw = open(DATA).read()
    data = json.loads(
        re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S).group(1)
    )
    venue_country = {v["id"]: v["country"] for v in data["venues"]}
    base = {t["code"]: t["baseRating"] for t in data["teams"]}
    P = load_params()

    def host_edge(code, venue):
        if code in HOSTS and venue and venue_country.get(venue) == HOST_COUNTRY[code]:
            return P["HOST_BONUS"]
        return 0.0

    def predict(ra, rb):
        diff = ra - rb
        p_a = 1 / (1 + 10 ** (-diff / P["LOGISTIC_DIV"]))
        draw = max(P["DRAW_FLOOR"], min(P["DRAW_CEIL"], P["DRAW_BASE"] - abs(diff) / P["DRAW_DIV"]))
        return [(1 - draw) * p_a, draw, (1 - draw) * (1 - p_a)]  # (p1, X, p2) team1 POV

    played = sorted(
        [m for m in data["matches"] if m["status"] == "completed" and m.get("score")],
        key=lambda m: m["dateET"],
    )
    n = len(played)
    if n == 0:
        print("no played games yet -- nothing to score")
        print("SCORE=inf")
        return

    ratings = dict(base)
    per_game_ll = []
    for m in played:
        t1, t2, v = m["team1"], m["team2"], m.get("venueId")
        ra = ratings[t1] + host_edge(t1, v)
        rb = ratings[t2] + host_edge(t2, v)
        probs = predict(ra, rb)
        g1, g2 = m["score"]["team1"], m["score"]["team2"]
        outcome = 0 if g1 > g2 else 2 if g2 > g1 else 1
        p = min(1 - EPS, max(EPS, probs[outcome]))
        per_game_ll.append(-math.log(p))
        # post-match Elo update, mirroring engine.js liveRatings (xG-tempered margin)
        w = 1.0 if g1 > g2 else 0.0 if g1 < g2 else 0.5
        exp = 1 / (1 + 10 ** (-((ratings[t1] + host_edge(t1, v)) - (ratings[t2] + host_edge(t2, v))) / P["LOGISTIC_DIV"]))
        ch = P["ELO_K"] * margin_mult(effective_gd(g1, g2, m.get("xg"), P["XG_TEMPER"])) * (w - exp)
        ratings[t1] += ch
        ratings[t2] -= ch

    all_ll = sum(per_game_ll) / n
    tail = per_game_ll[max(0, n - max(3, n // 3)):]
    tail_ll = sum(tail) / len(tail)

    drift = sum(((P[k] - SEED[k]) / SEED[k]) ** 2 for k in SEED)
    penalty = DRIFT_LAMBDA * drift
    score = all_ll + penalty

    print(f"games scored      : {n}")
    print(f"ALL_LL (in-sample): {all_ll:.5f}")
    print(f"TAIL_LL (last {len(tail)}) : {tail_ll:.5f}   <- watch this vs ALL_LL")
    print(f"drift penalty     : {penalty:.5f}  (raw drift {drift:.4f})")
    print(f"SCORE={score:.6f}")


if __name__ == "__main__":
    main()
