#!/usr/bin/env bash
# Run a Codex adversarial review of the current branch against main, in the foreground.
# Uses the official Codex plugin for Claude Code (openai/codex-plugin-cc).
# The review only sees COMMITTED work, so this refuses to run with uncommitted or
# untracked changes, whatever the local git settings say.
# Usage: scripts/codex-review.sh "<focus text>"
set -euo pipefail
STATUS="$(git status --porcelain --untracked-files=all)" || { echo "git status failed; not reviewing." >&2; exit 1; }
if [ -n "$STATUS" ]; then
  echo "Uncommitted changes found. The review only sees committed work: commit first, then re-run." >&2
  echo "$STATUS" >&2
  exit 1
fi
COMPANION="$(ls -d "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)"
if [ -z "$COMPANION" ]; then
  echo "Codex plugin not found. In Claude Code: /plugin install codex@openai-codex" >&2
  exit 1
fi
exec node "$COMPANION" adversarial-review --wait --base main "$*"
