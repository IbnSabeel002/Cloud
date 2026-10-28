#!/usr/bin/env bash
# Install the loop-engineering skills for every project on this machine (~/.claude/skills).
# Usage: scripts/install_loop_skills.sh [--force]
# Without --force, an existing skill with the same name is left alone and reported.
set -euo pipefail

src="$(cd "$(dirname "$0")/.." && pwd)/.claude/skills"
dest="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"
force=0
[[ "${1:-}" == "--force" ]] && force=1

mkdir -p "$dest"
for skill in loop-engineering verify-work goal-loop time-loop proactive-loop; do
  if [[ -e "$dest/$skill" && $force -eq 0 ]]; then
    echo "skip   $skill (already in $dest; rerun with --force to replace)"
    continue
  fi
  rm -rf "${dest:?}/$skill"
  cp -R "$src/$skill" "$dest/$skill"
  echo "install $skill -> $dest/$skill"
done
echo "Done. New sessions load them; type /loop-engineering to try."
