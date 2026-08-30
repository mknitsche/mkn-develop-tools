#!/usr/bin/env bash
# Ergaenzt den Signed-off-by-Trailer, wenn er fehlt.
#
# WARUM ALS HOOK UND NICHT ALS ERINNERUNG. Dieses Repository verlangt die
# Developer-Certificate-of-Origin-Zeile an jedem Commit (CONTRIBUTING.md), und
# die CI prueft sie -- aber erst im Pull Request, also lange nachdem die
# Commits geschrieben sind. In der Nacht zum 2026-08-30 sind so sieben PRs
# entstanden, deren DCO-Pruefung jedes Mal rot war; korrigierbar nur noch durch
# Umschreiben der Historie.
#
# Der Hook ERSETZT die Regel nicht, er erfuellt sie: die Zeile bedeutet, dass
# der Autor das Zertifikat anerkennt, und der Autor ist derselbe, dessen
# Identitaet git hier einsetzt.
set -euo pipefail
nachricht="$1"
grep -qi '^Signed-off-by: ' "$nachricht" && exit 0
name=$(git config user.name)
mail=$(git config user.email)
[ -n "$name" ] && [ -n "$mail" ] || { echo "user.name/user.email fehlen - kein Sign-off moeglich"; exit 1; }
printf '\nSigned-off-by: %s <%s>\n' "$name" "$mail" >> "$nachricht"
