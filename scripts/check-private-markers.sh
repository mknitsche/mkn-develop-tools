#!/usr/bin/env bash
# Fails when a tracked file carries a private path or an internal identifier.
#
# WHY THIS EXISTS. This repository is public. Comments and docstrings written
# in a private working session tend to carry session names, ticket numbers,
# rule numbers and real paths of the author's machines. None of that means
# anything to a reader here, and some of it identifies people and places.
# Cleaning it up once is not enough, so this guard stops the next one.
#
# What is rejected (one finding per line, printed as file:line):
#   - absolute home paths: /Users/<name>, /home/<name>, /root/
#   - /Volumes/<anything> except the placeholders YourDisk, SSD, Macintosh HD
#     and shell expressions such as /Volumes/* or "/Volumes/$name"
#   - internal ticket and rule numbers: TODO-n, PRJ-n, MS-n, HC-n, LP-n, ADR-n
#   - the author's internal contact id (the letters K, T, a hyphen and a digit)
#   - internal machine and session names: whole word macb, cld1 or macm,
#     optionally followed by -S<n> or -claude
#
# Skipped: CHANGELOG.md (written by the release tool), uv.lock, this file.
#
# The patterns are assembled from fragments so this file never matches itself.
# Exit status: 0 clean, 1 at least one finding.
set -euo pipefail

self="scripts/check-private-markers.sh"
cd "$(git rev-parse --show-toplevel)"

# A pattern starts at a non-word character (or the line start) so that words
# merely containing a name do not trip it.
lead='(^|[^[:alnum:]_])'
tail='([^[:alnum:]_]|$)'

users="/Use""rs/[^/[:space:]]+"
home="/ho""me/[^/[:space:]]+"
root="/ro""ot/"
kt="K""T-[0-9]"
ids="(TO""DO|PR""J|M""S|H""C|L""P|AD""R)-[0-9]+"
hosts="(ma""cb|cl""d1|ma""cm)(-S[0-9]+|-claude)?"
vol="/Vol""umes/"

# git grep exits 0 on a match, 1 on none, >1 on a real error. It searches the
# tracked files only, so untracked and ignored files are never looked at.
SCAN_OUT=""
scan() { # scan <label> <pattern> [-o]; result in SCAN_OUT
  local label="$1" pattern="$2" only="${3:-}" status=0
  SCAN_OUT=$(git grep -nIE $only -e "$pattern" -- . ":!CHANGELOG.md" ":!uv.lock" ":!${self}") || status=$?
  if [ "$status" -gt 1 ]; then
    echo "check-private-markers: git grep failed for '$label' (exit $status)" >&2
    exit 2
  fi
}

found=0
report() { # report <label>: prints file:line for every line in SCAN_OUT
  [ -n "$SCAN_OUT" ] || return 0
  found=1
  while IFS= read -r line; do
    printf '%s: %s\n' "$(printf '%s' "$line" | cut -d: -f1,2)" "$1"
  done <<<"$SCAN_OUT"
}

scan users "${lead}(${users}|${home}|${root})"
report "absolute user path"
# -o prints each occurrence on its own, so a line that mixes an allowed and a
# forbidden volume is still caught.
scan vol "${vol}[[:alnum:]_]+( [[:alnum:]_]+)?" -o
SCAN_OUT=$(printf '%s\n' "$SCAN_OUT" | grep -vE ":${vol}(YourDisk|SSD|Macintosh HD)$" || [ $? -eq 1 ])
report "external volume path"
scan kt "${lead}${kt}"
report "internal contact id"
scan ids "${lead}${ids}"
report "internal ticket or rule number"
scan hosts "${lead}${hosts}${tail}"
report "internal machine or session name"

if [ "$found" -ne 0 ]; then
  echo "check-private-markers: private path or internal identifier found (see CONTRIBUTING.md)." >&2
  exit 1
fi
