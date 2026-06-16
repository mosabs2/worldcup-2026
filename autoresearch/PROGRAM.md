# PROGRAM.md — auto-research instructions (human-only)

This is the **instructions file** in Karpathy's three-file auto-research pattern.
The human (Mohammed) edits this. The agent reads it, never edits it. It tells the
agent what to improve, what it may touch, and the rules it must obey.

## Goal

Lower the World Cup probability model's **multiclass log-loss** on the 2026
matches that have actually been played, by tuning the model's global constants.
Sharper pre-match 1X2 probabilities = lower SCORE.

## The asset you may change

`autoresearch/params.json` — and **nothing else**. It holds eight global
constants seeded at the live `engine.js` values. You propose new values, the
scorer judges them, the driver keeps the change only if SCORE drops.

You may NOT:
- edit `autoresearch/score.py` (the scorer) — that is cheating the metric;
- edit `src/engine.js`, `src/data.js`, or any team's `baseRating` — the 48 base
  ratings are frozen on purpose (48 free knobs on 14 games overfits instantly);
- add new keys to `params.json` or remove existing ones.

## How you are scored

`python3 autoresearch/score.py` reads `params.json`, replays the model with no
look-ahead, and prints `SCORE=<float>` on its last line. Lower is better. The
score is in-sample log-loss plus a fixed drift penalty that punishes moving a
constant far from its reasoned seed. You cannot see or change the penalty weight.

## Hard rules (the n=14 problem — read this)

There are only **14 played games**. This fails Karpathy's own "high volume of
feedback" criterion, so overfitting is the default outcome, not a risk to manage
later. Therefore:

1. **Move one or two constants at a time**, not all eight. Small steps.
2. **A real improvement is small and survives the tail.** After any proposal
   that lowers SCORE, check the printed `TAIL_LL`. If ALL_LL fell but TAIL_LL
   rose, you overfit — revert and try a different direction.
3. **Prefer the smallest change that helps.** A 0.001 SCORE drop from a 50%
   parameter swing is noise; ignore it.
4. **Stop early.** Target at most ~30 iterations. If three consecutive proposals
   fail to lower SCORE by more than 0.002, stop and report — do not grind.
5. Never disable, bypass, or "temporarily edit" the scorer or its bounds.

## Recommended search order (most to least defensible)

1. `LOGISTIC_DIV` — sets how steeply rating gaps map to win probability; the most
   likely genuinely-miscalibrated knob.
2. `DRAW_BASE` and `DRAW_DIV` — the draw rate. The opening round had several
   draws (CAN-BIH, QAT-SUI, BRA-MAR, NED-JPN, ESP-CPV, BEL-EGY); the model may be
   under-weighting draws.
3. `ELO_K` — how fast ratings move per game.
4. `HOST_BONUS`, `XG_TEMPER` — leave near seed unless 1-3 clearly help.

## What to report at the end

The best `params.json` found, its SCORE, ALL_LL and TAIL_LL, which constants
moved and by how much, and an honest one-line read on whether the gain looks
real or like sample-fitting. Promotion into `engine.js` is the human's call
(see README.md), not yours.
