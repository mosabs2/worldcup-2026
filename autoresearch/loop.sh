#!/usr/bin/env bash
# loop.sh — the auto-research driver (Karpathy's "run it while you sleep" loop).
#
# Each iteration: snapshot params.json, ask the agent to propose a new params.json
# guided by PROGRAM.md, re-score, keep the change if SCORE dropped, else revert.
# The agent only ever touches params.json; score.py is the locked judge.
#
# This is the LLM-driven version (the thing the video is selling). For eight
# numeric knobs it is the showy option, not the best one -- see sweep.py for the
# deterministic coordinate search, which is faster, free, and reproducible. Use
# this loop only if you specifically want the LLM-in-the-loop behaviour.
#
# Usage:  ./autoresearch/loop.sh [max_iters]   (default 20)
# Requires: the `claude` CLI on PATH. Run from the repo root.

set -euo pipefail
cd "$(dirname "$0")/.."
DIR=autoresearch
MAX="${1:-20}"
LOG="$DIR/experiments.log"

score() { python3 "$DIR/score.py" | sed -n 's/^SCORE=//p'; }

best=$(score)
echo "$(date '+%F %T')  baseline SCORE=$best" | tee -a "$LOG"

for i in $(seq 1 "$MAX"); do
  cp "$DIR/params.json" "$DIR/params.prev.json"

  # The agent reads the instructions + current params + last score, and rewrites
  # params.json in place. --allowedTools limits it to editing that one file.
  claude -p "Read $DIR/PROGRAM.md and $DIR/params.json. The current SCORE is $best \
(lower is better). Propose ONE improved params.json per the rules in PROGRAM.md \
and write it back to $DIR/params.json. Change one or two constants only. Do not \
touch any other file." \
    --allowedTools "Read,Edit,Write" >/dev/null 2>&1 || true

  new=$(score) || new=inf
  if awk "BEGIN{exit !($new < $best)}"; then
    echo "$(date '+%F %T')  iter $i KEEP   $best -> $new" | tee -a "$LOG"
    best="$new"
  else
    cp "$DIR/params.prev.json" "$DIR/params.json"
    echo "$(date '+%F %T')  iter $i revert $new (kept $best)" | tee -a "$LOG"
  fi
done

rm -f "$DIR/params.prev.json"
echo "$(date '+%F %T')  done. best SCORE=$best" | tee -a "$LOG"
echo "Review autoresearch/params.json and the TAIL_LL diagnostic before promoting to engine.js."
