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

# A finite decimal? (rejects inf / nan / empty / error text). Critical: awk reads a
# bareword `inf` as an uninitialised variable = 0, so a naive `$new < $best` would
# wrongly KEEP an out-of-bounds proposal (SCORE=inf) and then wedge the loop into
# permanent-revert. Validate the string as a number first. The regex is a literal in
# the awk program (not passed via -v, where BSD awk would strip the `\.` escape).
isnum() { awk -v x="$1" 'BEGIN{exit !(x ~ /^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$/)}'; }
# better NEW BEST -> success iff NEW is a finite number strictly below BEST.
better() { awk -v n="$1" -v b="$2" 'BEGIN{
  if (n !~ /^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$/) exit 1;   # NEW not finite -> never keep
  if (b !~ /^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$/) exit 0;   # BEST not numeric -> any valid NEW wins
  exit !(n+0 < b+0) }'; }

# Enforce the score.py / PROGRAM.md lock OUTSIDE the model's honour system. The agent
# is told to touch only params.json, but --allowedTools restricts the TOOLS, not the
# file paths — Edit/Write can hit any file. Snapshot the judge files now and restore
# them from the snapshot if the agent modifies them, so it cannot game the metric.
LOCKED=("$DIR/score.py" "$DIR/PROGRAM.md" "$DIR/sweep.py")
LOCKDIR="$(mktemp -d)"
trap 'rm -rf "$LOCKDIR" "$DIR/params.prev.json"' EXIT
for f in "${LOCKED[@]}"; do [ -f "$f" ] && cp "$f" "$LOCKDIR/$(basename "$f")"; done
restore_locked() {
  local changed=0 f
  for f in "${LOCKED[@]}"; do
    [ -f "$LOCKDIR/$(basename "$f")" ] || continue
    if ! cmp -s "$f" "$LOCKDIR/$(basename "$f")"; then
      cp "$LOCKDIR/$(basename "$f")" "$f"; changed=1
    fi
  done
  [ "$changed" = 1 ] && echo "$(date '+%F %T')  WARNING: agent edited a locked file; restored from snapshot" | tee -a "$LOG"
  return 0
}

best=$(score)
if ! isnum "$best"; then
  echo "$(date '+%F %T')  baseline SCORE is not a finite number ($best); fix autoresearch/params.json first." | tee -a "$LOG"
  exit 1
fi
echo "$(date '+%F %T')  baseline SCORE=$best" | tee -a "$LOG"

for i in $(seq 1 "$MAX"); do
  cp "$DIR/params.json" "$DIR/params.prev.json"

  # The agent reads the instructions + current params + last score, and rewrites
  # params.json in place. It is only allowed to touch that one file; restore_locked
  # below undoes any tampering with the judge files regardless of what it does.
  claude -p "Read $DIR/PROGRAM.md and $DIR/params.json. The current SCORE is $best \
(lower is better). Propose ONE improved params.json per the rules in PROGRAM.md \
and write it back to $DIR/params.json. Change one or two constants only. Do not \
touch any other file." \
    --allowedTools "Read,Edit,Write" >/dev/null 2>&1 || true

  restore_locked

  new=$(score) || new=""
  if better "$new" "$best"; then
    echo "$(date '+%F %T')  iter $i KEEP   $best -> $new" | tee -a "$LOG"
    best="$new"
  else
    cp "$DIR/params.prev.json" "$DIR/params.json"
    echo "$(date '+%F %T')  iter $i revert ${new:-<non-numeric>} (kept $best)" | tee -a "$LOG"
  fi
done

rm -f "$DIR/params.prev.json"
echo "$(date '+%F %T')  done. best SCORE=$best" | tee -a "$LOG"
echo "Review autoresearch/params.json and the TAIL_LL diagnostic before promoting to engine.js."
