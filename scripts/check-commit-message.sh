#!/usr/bin/env bash
# Conventional Commits, checked on the message file passed by the commit-msg hook.
set -euo pipefail

datei="${1:?commit message file expected}"
# Kommentarzeilen und Leerzeilen weg, dann die erste echte Zeile nehmen.
betreff="$(grep -v '^#' "$datei" | grep -v '^[[:space:]]*$' | head -1 || true)"

# Merge- und Revert-Commits erzeugt git selbst; sie folgen dem Schema nicht.
case "$betreff" in
  Merge\ *|Revert\ *) exit 0 ;;
esac

muster='^(feat|fix|docs|refactor|test|chore|perf|build|ci)(\([a-z0-9._-]+\))?!?: .+'
if ! printf '%s' "$betreff" | grep -Eq "$muster"; then
  cat >&2 <<MSG
Commit message does not follow Conventional Commits.

  got:      $betreff
  expected: type(scope): summary
  types:    feat fix docs refactor test chore perf build ci

See CONTRIBUTING.md.
MSG
  exit 1
fi
