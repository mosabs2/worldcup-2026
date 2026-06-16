# autoresearch — Karpathy auto-research loop for the WC probability model

A self-contained sandbox that applies Karpathy's three-file auto-research pattern
to this repo's prediction model. It does **not** touch the live model: it tunes a
copy of the constants and leaves promotion to you.

## The three files (Karpathy's pattern)

| Karpathy | here | who edits it |
|----------|------|--------------|
| instructions / `program.md` | `PROGRAM.md` | you (human) |
| the asset to optimise | `params.json` (8 model constants) | the agent |
| scoring (locked) | `score.py` (walk-forward log-loss + drift penalty) | nobody — locked |

Two drivers sit on top:
- `sweep.py` — deterministic coordinate search. **Use this.** Free, instant, reproducible.
- `loop.sh` — the LLM-in-the-loop version (what the video sells). Slower, costs
  tokens, non-deterministic. Use only if you want LLM-style reasoning over the knobs.

## Run it

```bash
python3 autoresearch/score.py          # score current params.json
python3 autoresearch/sweep.py          # search, print best, DRY RUN (no write)
python3 autoresearch/sweep.py --write  # search and save best into params.json
./autoresearch/loop.sh 20              # LLM loop, 20 iterations (needs `claude` CLI)
```

## The promotion gate (the part that matters)

A lower SCORE is **not** permission to ship. Before copying any tuned constant
into `src/engine.js`, all of these must hold:

1. **TAIL_LL moved with ALL_LL.** If in-sample log-loss fell but the last-third
   log-loss rose, it's overfit. Reject.
2. **No constant slammed into a `BOUNDS` edge.** A knob pinned at its min/max
   means the optimiser wanted to run away — a classic small-sample artefact, not
   a real signal. Reject or widen your thinking, don't ship it.
3. **The move is physically defensible**, not just numerically better. "Predict
   more draws because the opening round had lots of draws" is sample-chasing;
   "the host edge is a bit bigger than 55" is arguable. Sniff-test every move.
4. **n is big enough to mean anything.** At ~14 games, treat every result as
   directional only. Re-run after each matchday; trust it more as n grows past
   ~40, and a lot more once the group stage (72 games) is complete.

If it passes, change the constant in BOTH `src/engine.js` and the `SEED` dict in
`score.py` (so the penalty re-anchors), commit, and let the site rebuild.

## Why this is sandboxed

The live published probabilities should never be silently mutated by an overnight
loop fitting 8 knobs to a dozen games. The loop optimises a copy; you decide what,
if anything, graduates. That is the single most important design choice here, and
it is the opposite of the video's "let it run while you sleep" pitch.
