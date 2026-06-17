#!/bin/zsh
# Reliable trigger for the worldcup-2026 auto-update workflow.
#
# Why this exists: GitHub's own scheduled cron (the `schedule:` triggers in
# auto-update.yml) is best-effort and routinely drops runs, so during matches the
# published site can lag the final whistle by hours. This script runs on the
# always-on Mac mini's cron — which keeps good time — and fires a GitHub
# `workflow_dispatch`, which executes immediately and is not subject to the
# schedule-drop problem. The GitHub Action still does all the work; this just
# guarantees the trigger fires. The repo's own schedule stays on as a fallback.
#
# Auth: a fine-grained GitHub PAT (repo mosabs2/worldcup-2026, permission
# "Actions: Read and write") in ~/.claude/worldcup-gh-token (0600, machine-local,
# never in the vault or git). Headless SSH can't read gh's keychain token, hence
# the file. Until the token is in place this script logs and exits cleanly.
#
# Deployed copy: ~/.claude/jobs/run-worldcup-dispatch.sh on the mini.
# Cron (mini, London local; the tournament runs entirely within BST):
#   */5 17-23,0-7 * * *   = every 5 min across 16:00-06:59 UTC, the match window.
# Self-terminates after the final (19 July 2026).

TOKEN_FILE="$HOME/.claude/worldcup-gh-token"
LOGDIR="$HOME/.claude/jobs/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/worldcup-dispatch-$(date '+%Y-%m-%d').log"
DATE=$(date '+%Y-%m-%d')

# Tournament guard: stop after the final.
[[ "$DATE" > "2026-07-20" ]] && exit 0

if [ ! -s "$TOKEN_FILE" ]; then
  echo "$(date '+%H:%M') no token at $TOKEN_FILE yet — skipping dispatch" >> "$LOG"
  exit 0
fi

TOKEN=$(cat "$TOKEN_FILE")
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/mosabs2/worldcup-2026/actions/workflows/auto-update.yml/dispatches" \
  -d '{"ref":"main"}')
# 204 = accepted; anything else is logged so a bad/expired token is visible.
echo "$(date '+%H:%M') workflow_dispatch -> HTTP $CODE" >> "$LOG"
