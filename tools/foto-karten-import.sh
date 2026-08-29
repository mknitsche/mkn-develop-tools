#!/bin/bash
# foto-karten-import — Kamerakarten nach Mac UND SSD sichern, in KT-1s Ordnerschema.
#
# Erkennt eingelegte Karten am DCIM-Ordner (nicht am Volume-Namen — die Fuji-Karte
# heisst "Untitled", das waere mit einem beliebigen USB-Stick verwechselbar).
#
# Zielschema:
#   <ZIEL>/<Ereignis>/<AUFNAHMETAG>/<Kamera>/DATEIEN
#
# AUFNAHMETAG kommt aus dem EXIF jeder EINZELNEN Datei (sips), nicht vom Kopiertag:
# wer zwei Tage auf einmal einliest, bekommt zwei Zielordner. RAW+JPEG-Paare mit
# gleichem Basisnamen erhalten IMMER dasselbe Datum und werden nie getrennt.
#
# LOESCHT NIE etwas — weder auf der Karte noch am Ziel. Formatieren bleibt Handarbeit.
# Mehrfach aufrufbar: kopiert nur, was fehlt (rsync), nach Abbruch fortsetzbar.
#
# WOHNORT: mkn-develop-tools/tools/. Das ist ein WERKZEUG und gehoert nicht in das
# persoenliche Wissenssystem — das Kriterium ist die Zugehoerigkeit, nicht die
# Technik. In ~/.local/bin liegt nur ein Symlink darauf (Muster wie macb-launch):
# EINE Datei, keine zwei Kopien, die auseinanderdriften koennen.
#
# Historie: bis 2026-08-28 ungesichert und ungetrackt in ~/.local/bin, dann in
# claudeAI/system/scripts/, seit 2026-08-29 hier.
#
# OFFEN: dieses Skript hat KEINE Tests. Das widerspricht der Latte dieses Repos
# und ist bewusst benannt statt versteckt — die heikle Stelle ist `datum_je_datei`,
# die entscheidet, in welchen Tagesordner ein Bild wandert.

set -uo pipefail

# Zielorte. Beide sind ueberschreibbar — als Umgebungsvariable oder ueber
# --mac / --ssd. Ein Werkzeug, das fremde Rechner nicht kennt, darf seine
# eigenen Ordner nicht als Naturgesetz behandeln.
MAC_BASIS="${FOTO_ZIEL_MAC:-$HOME/Pictures/01 Bilder von Camera}"
SSD_BASIS="${FOTO_ZIEL_SSD:-}"

EREIGNIS=""
TROCKEN=0
NUR_DATUM=""

hilfe() {
    cat <<'ENDE'
foto-karten-import [Optionen]

  --mac PFAD          Erstes Ziel (Standard: $FOTO_ZIEL_MAC oder ~/Pictures/...)
  --ssd PFAD          Zweites Ziel (Pflicht, oder $FOTO_ZIEL_SSD)
  --ereignis "NAME"   Ereignis-Ordner (Standard: juengster im Bestand)
  --nur YYYY-MM-DD    Nur Aufnahmen dieses Tages uebertragen
  --trocken           Nur zeigen, was passieren wuerde
  --hilfe             Diese Hilfe

Sortiert nach AUFNAHMETAG aus dem EXIF, nicht nach Kopiertag.
RAW+JPEG-Paare bleiben zusammen. Loescht nie etwas.
ENDE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --mac)      MAC_BASIS="${2:-}";  shift 2 ;;
        --ssd)      SSD_BASIS="${2:-}";  shift 2 ;;
        --ereignis) EREIGNIS="${2:-}";   shift 2 ;;
        --nur)      NUR_DATUM="${2:-}";  shift 2 ;;
        --trocken)  TROCKEN=1;           shift ;;
        --hilfe|-h) hilfe; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; hilfe >&2; exit 2 ;;
    esac
done

if [ -n "$NUR_DATUM" ] && ! echo "$NUR_DATUM" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
    echo "FEHLER: --nur muss YYYY-MM-DD sein, war: '$NUR_DATUM'" >&2
    exit 2
fi

# --- Vorbedingungen -----------------------------------------------------------
[ -d "$MAC_BASIS" ] || { echo "FEHLER: Mac-Basis fehlt: $MAC_BASIS" >&2; exit 1; }
if [ -z "$SSD_BASIS" ]; then
    echo "FEHLER: Kein zweites Ziel angegeben." >&2
    echo "        Erwartet wird FOTO_ZIEL_SSD oder --ssd \"/Pfad/zur/Sicherung\"." >&2
    echo "        Zwei Ziele sind Absicht: eine einzige Kopie ist keine Sicherung." >&2
    exit 1
fi
if [ ! -d "$SSD_BASIS" ]; then
    echo "FEHLER: Zweites Ziel nicht gefunden ($SSD_BASIS)." >&2
    echo "        Ist der Datentraeger angesteckt und eingehaengt?" >&2
    exit 1
fi
command -v sips >/dev/null || { echo "FEHLER: sips fehlt (fuer EXIF noetig)." >&2; exit 1; }

# Ereignis = juengster Ordner, der wie ein Ereignis AUSSIEHT (beginnt mit Jahreszahl).
# Ohne diesen Filter wird jeder beliebige Ordner zum Ziel, sobald er zufaellig der
# zuletzt angefasste ist — beim Testen hat genau das einen Hilfsordner gewaehlt.
if [ -z "$EREIGNIS" ]; then
    EREIGNIS="$(ls -t "$MAC_BASIS" 2>/dev/null | grep -E '^[0-9]{4}-' | head -1)"
    if [ -z "$EREIGNIS" ]; then
        echo "FEHLER: kein Ereignis-Ordner (Name beginnt mit JJJJ-) gefunden." >&2
        echo "        Vorhanden:" >&2; ls -1 "$MAC_BASIS" | sed 's/^/          /' >&2
        echo "        Mit --ereignis \"NAME\" ausdruecklich waehlen." >&2
        exit 1
    fi
fi

ARBEIT="$(mktemp -d "${TMPDIR:-/tmp}/fotoimport.XXXXXX")" || exit 1
trap 'rm -rf "$ARBEIT"' EXIT INT TERM

# --- Karten finden ------------------------------------------------------------
karten_finden() {
    local vol dcim unter
    for vol in /Volumes/*; do
        [ -d "$vol" ] || continue
        [ "$vol" = "/Volumes/Macintosh HD" ] && continue
        dcim="$vol/DCIM"
        [ -d "$dcim" ] || continue
        for unter in "$dcim"/*; do
            [ -d "$unter" ] || continue
            case "$(basename "$unter")" in
                *ND850*) echo "D850|$unter" ;;
                *FUJI*)  echo "X-E5|$unter" ;;
                *CANON*) echo "Canon|$unter" ;;
                *)       echo "UNBEKANNT-$(basename "$unter")|$unter" ;;
            esac
        done
    done
}

FUNDE=()
while IFS= read -r zeile; do
    [ -n "$zeile" ] && FUNDE+=("$zeile")
done < <(karten_finden)

if [ "${#FUNDE[@]}" -eq 0 ]; then
    echo "Keine Kamerakarte gefunden (gesucht nach DCIM-Ordnern unter /Volumes/)."
    echo "Eingehaengt sind gerade:"; ls -1 /Volumes/ | sed 's/^/  /'
    exit 1
fi

echo "════════════════════════════════════════════════════════════════"
echo "  Ereignis : $EREIGNIS"
echo "  Sortierung: nach Aufnahmetag (EXIF)"
[ -n "$NUR_DATUM" ]  && echo "  Filter   : nur Aufnahmen vom $NUR_DATUM"
[ "$TROCKEN" -eq 1 ] && echo "  MODUS    : TROCKENLAUF — es wird nichts geschrieben"
echo "════════════════════════════════════════════════════════════════"

# Listet die Dateien aus $2, fuer die $1 noch kein Datum hat.
offene_liste() {
    awk -F'\t' 'NR==FNR { hat[$2] = 1; next } !($0 in hat)' "$1" "$2"
}

# --- Datum je Datei bestimmen -------------------------------------------------
# Schreibt "<DATUM>\t<PFAD>" nach $1. Dreistufig, weil kein einzelnes Werkzeug
# alle Formate beantwortet:
#   1. sips     — schnell, im Stapel, beantwortet Fotos
#   2. exiftool — beantwortet Video und alles, was sips nicht kennt
#   3. mtime    — letzte Rueckfallebene: eine Datei ohne Datum darf nicht verschwinden
#
# Warum Stufe 2 (Befund 2026-08-28): sips liefert fuer Videos die Zeile
# "creation: <nil>". Die galt frueher als gueltige Antwort — "<nil>" wurde als
# Datum uebernommen, die Datei war damit "beantwortet", und der mtime-Rueckfall
# konnte nie greifen. Ergebnis war ein Zielordner namens "<nil>". Videos gibt es
# bei der Fuji, kuenftig auch bei Nikon.
#
# Danach Paar-Bindung: alle Dateien mit gleichem Basisnamen erben das FRUEHESTE
# Datum ihrer Gruppe, damit RAW und JPEG nie in verschiedenen Ordnern landen.
datum_je_datei() {
    local quelle="$1" ziel="$2"
    local roh="$ARBEIT/roh.txt" alle="$ARBEIT/alle.txt" offen="$ARBEIT/offen.txt"
    : > "$roh"
    find "$quelle" -type f ! -name '.*' > "$alle"

    # Stufe 1: sips im Stapel. Uebernommen wird NUR ein echtes Datum — alles
    # andere ("<nil>") faellt durch, damit Stufe 2 es sieht.
    # -print0/-0 beibehalten: xargs auf macOS kennt weder -a noch -d.
    find "$quelle" -type f ! -name '.*' -print0 \
        | xargs -0 sips -g creation 2>/dev/null \
        | awk '
            /^\// { pfad = $0; next }
            /creation:/ && pfad != "" {
                d = $2
                if (d ~ /^[0-9][0-9][0-9][0-9]:[0-9][0-9]:[0-9][0-9]$/) {
                    gsub(/:/, "-", d)
                    print d "\t" pfad
                }
                pfad = ""
            }
        ' > "$roh"

    offene_liste "$roh" "$alle" > "$offen"

    # Stufe 2: exiftool. DateTimeOriginal steht ZUERST, weil es lokale Zeit
    # traegt; QuickTime-Zeiten sind UTC und ergaeben kurz vor Mitternacht den
    # falschen Tag. exiftool haelt die angefragte Reihenfolge ein (belegt).
    if [ -s "$offen" ]; then
        if command -v exiftool >/dev/null 2>&1; then
            while IFS= read -r f; do
                d="$(exiftool -q -m -d '%Y-%m-%d' -s -s -s \
                        -DateTimeOriginal -CreateDate -MediaCreateDate "$f" 2>/dev/null \
                     | awk '/^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/ { print; exit }')"
                [ -n "$d" ] && printf '%s\t%s\n' "$d" "$f"
            done < "$offen" >> "$roh"
            offene_liste "$roh" "$alle" > "$offen"
        else
            echo "     WARNUNG: exiftool fehlt — $(wc -l < "$offen" | tr -d ' ') Datei(en)" \
                 "(Video?) bekommen das Datei-Datum statt des Aufnahmedatums." >&2
        fi
    fi

    # Stufe 3: mtime. Lieber ein leicht falscher Ordner als gar keiner.
    while IFS= read -r f; do
        printf '%s\t%s\n' "$(stat -f '%Sm' -t '%Y-%m-%d' "$f")" "$f"
    done < "$offen" >> "$roh"

    # Paar-Bindung ueber den Basisnamen ohne Endung.
    awk -F'\t' '
        {
            n = split($2, teile, "/")
            name = teile[n]
            sub(/\.[^.]*$/, "", name)
            if (!(name in fruehestes) || $1 < fruehestes[name]) fruehestes[name] = $1
            zeilen[NR] = $0
            basis[NR]  = name
        }
        END { for (i = 1; i <= NR; i++) {
                  split(zeilen[i], s, "\t")
                  print fruehestes[basis[i]] "\t" s[2]
              } }
    ' "$roh" | sort > "$ziel"
}

GESAMT_OK=0
GESAMT_FEHLER=0

for fund in "${FUNDE[@]}"; do
    KAMERA="${fund%%|*}"
    QUELLE="${fund#*|}"
    ANZAHL=$(find "$QUELLE" -type f ! -name '.*' | wc -l | tr -d ' ')

    echo
    echo "──── $KAMERA — $ANZAHL Dateien auf der Karte"
    echo "     Lese Aufnahmedaten ..."
    KARTE_MAP="$ARBEIT/map-$KAMERA.txt"
    datum_je_datei "$QUELLE" "$KARTE_MAP"

    TAGE=$(cut -f1 "$KARTE_MAP" | sort -u)
    [ -n "$NUR_DATUM" ] && TAGE=$(echo "$TAGE" | grep -x "$NUR_DATUM")

    if [ -z "$TAGE" ]; then
        echo "     Keine passenden Aufnahmen."
        continue
    fi

    for TAG in $TAGE; do
        LISTE="$ARBEIT/liste.txt"
        awk -F'\t' -v t="$TAG" '$1 == t { print $2 }' "$KARTE_MAP" > "$LISTE"
        N=$(wc -l < "$LISTE" | tr -d ' ')

        MAC_ZIEL="$MAC_BASIS/$EREIGNIS/$TAG/$KAMERA"
        SSD_ZIEL="$SSD_BASIS/$EREIGNIS/$TAG/$KAMERA"

        echo "     $TAG — $N Datei(en) → $EREIGNIS/$TAG/$KAMERA/"

        if [ "$TROCKEN" -eq 1 ]; then
            continue
        fi

        mkdir -p "$MAC_ZIEL" "$SSD_ZIEL" || { echo "       FEHLER: Ziel nicht anlegbar" >&2; GESAMT_FEHLER=$((GESAMT_FEHLER+1)); continue; }

        # Karte -> Mac (nur die Dateien dieses Tages)
        echo -n "       Mac  ... "
        if rsync -a --partial --no-relative --files-from="$LISTE" / "$MAC_ZIEL/" 2>/dev/null; then
            echo "ok"
        else
            echo "FEHLGESCHLAGEN"; GESAMT_FEHLER=$((GESAMT_FEHLER+1)); continue
        fi

        # Mac -> SSD (die Karte ist der langsamste Teil und wird nicht erneut gelesen)
        echo -n "       SSD  ... "
        if rsync -a --partial --exclude='.*' "$MAC_ZIEL/" "$SSD_ZIEL/" 2>/dev/null; then
            echo "ok"
        else
            echo "FEHLGESCHLAGEN"; GESAMT_FEHLER=$((GESAMT_FEHLER+1)); continue
        fi

        # Beweis: beide Ziele per Pruefsumme gegen die KARTE — nicht gegeneinander,
        # ein gemeinsamer Lesefehler waere sonst auf beiden Seiten gleich falsch.
        ABW_MAC=$(rsync -acn --no-relative --files-from="$LISTE" --out-format='%n' / "$MAC_ZIEL/" 2>/dev/null | grep -cv '/$')
        ABW_SSD=$(rsync -acn --no-relative --files-from="$LISTE" --out-format='%n' / "$SSD_ZIEL/" 2>/dev/null | grep -cv '/$')

        if [ "$ABW_MAC" -eq 0 ] && [ "$ABW_SSD" -eq 0 ]; then
            echo "       Pruefsummen: Mac und SSD bitgleich mit der Karte ($N Dateien)"
            GESAMT_OK=$((GESAMT_OK + N))
        else
            echo "       WARNUNG: Mac weicht bei $ABW_MAC ab, SSD bei $ABW_SSD"
            echo "       -> NICHT formatieren. Erneut aufrufen; bleibt es, Karte pruefen."
            GESAMT_FEHLER=$((GESAMT_FEHLER+1))
        fi
    done
done

# ── Gesamtabgleich Mac → SSD ────────────────────────────────────────────────
# Ueber den GESAMTEN Baum, nicht nur ueber das heutige Ereignis: Bearbeitung
# (Lightroom/Capture One) faellt nicht am Import-Tag an und aendert .xmp-Sidecars
# quer durch den Bestand — auch in Ordnern, die seit Wochen kein Lauf beruehrt hat.
# Die Tages-Schleife oben kann das konstruktiv nicht sehen: sie kennt nur die Tage,
# die heute von der Karte kamen. Gemessen 2026-08-25: 86 Sidecars lagen einseitig
# auf dem Mac, waehrend die des am selben Tag zufaellig erneut beruehrten
# Nachbarordners gespiegelt waren.
#
# NIEMALS loeschen (kein --delete): die SSD ist Sicherung, kein Spiegel. Was auf
# dem Mac beim Aussortieren verschwindet, bleibt hier erhalten.
if [ -d "$MAC_BASIS" ]; then
    echo
    echo "──── Gesamtabgleich Mac → SSD"

    PLAN="$ARBEIT/abgleich.txt"
    rsync -a -n --exclude='.*' --exclude='_Rejected/' --out-format='%n' "$MAC_BASIS/" "$SSD_BASIS/" 2>/dev/null \
        | grep -v '/$' > "$PLAN" || true
    OFFEN=$(wc -l < "$PLAN" | tr -d ' ')

    if [ "$OFFEN" -eq 0 ]; then
        echo "     Nichts offen — SSD ist auf Stand."
    else
        # Aufgeschluesselt, damit eine Zahl nie fuer sich allein steht.
        N_XMP=$(grep -ci '\.xmp$' "$PLAN" || true)
        N_BILD=$(grep -ciE '\.(jpg|jpeg|nef|raf|dng|tif|tiff|mov|mp4)$' "$PLAN" || true)
        N_REST=$((OFFEN - N_XMP - N_BILD))
        echo "     Offen: $N_XMP Bearbeitung, $N_BILD Bild/Video, $N_REST sonstige"
        if [ "$TROCKEN" -eq 1 ]; then
            echo "     (Trockenlauf — nichts geschrieben)"
        elif rsync -a --exclude='.*' --exclude='_Rejected/' "$MAC_BASIS/" "$SSD_BASIS/" 2>/dev/null; then
            echo "     $OFFEN Datei(en) auf die SSD gesichert."
        else
            echo "     FEHLGESCHLAGEN — Stand liegt nur auf dem Mac." >&2
            GESAMT_FEHLER=$((GESAMT_FEHLER+1))
        fi
    fi
fi

echo
echo "════════════════════════════════════════════════════════════════"
if [ "$TROCKEN" -eq 1 ]; then
    echo "  Trockenlauf beendet — nichts geschrieben."
    exit 0
fi
if [ "$GESAMT_FEHLER" -eq 0 ]; then
    echo "  FERTIG — $GESAMT_OK Dateien auf Mac UND SSD, per Pruefsumme belegt."
    echo "  Karten koennen formatiert werden."
else
    echo "  MIT FEHLERN BEENDET ($GESAMT_FEHLER) — Karten NICHT formatieren."
fi
echo "════════════════════════════════════════════════════════════════"
[ "$GESAMT_FEHLER" -eq 0 ] || exit 1
