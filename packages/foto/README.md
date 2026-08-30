# mkn-foto

Tools for a photo workflow: read a shooting tree, recognise series, resolve
places from a GPS track, and write that back into the files — so the
information travels with the image rather than living in one program's
database.

## External requirement

**ExifTool** must be on `PATH`. It is invoked as an external programme and is
not bundled; it carries its own licence (Artistic/GPL, by Phil Harvey).

```
macOS    brew install exiftool
Debian   apt install libimage-exiftool-perl
Windows  https://exiftool.org  (exiftool.exe on PATH)
```

Nothing else is required — no database, no network, no account.

## Getting started

Four steps. Nothing is installed system-wide, nothing is sent anywhere you did
not configure.

**1 — Tell the tool who you are and what you have.** One file, at
`~/.config/mkn-foto/konfig.json`, or wherever `MKN_FOTO_KONFIG` points:

```json
{
  "ziel": "/Volumes/YourDisk/enriched",
  "schluessel_datei": "~/.config/mkn-foto/keys.json",
  "modell": {"anbieter": "anthropic", "name": "claude-opus-5"},
  "urheber": {
    "name": "Erika Muster",
    "stadt": "Munich",
    "land": "Germany",
    "email": "erika@example.org",
    "website": "https://example.org"
  }
}
```

Every field may be left out. Without `urheber` no authorship is written; without
`modell` no model is asked and the tool runs on camera facts alone; without
`ziel` the destination comes from the call.

**2 — Put your API key somewhere else.** The configuration names the *place* of
the key file, never the key. A configuration travels into backups, templates and
the occasional screenshot; a key should not.

```json
{"anthropic": "sk-ant-...", "gemini": "..."}
```

One file can hold several providers. A single key may also be stored under
`api_key`, so someone with one provider need not know its name.

Precedence, highest first: the provider's own environment variable
(`ANTHROPIC_API_KEY`, …), then `MKN_LLM_SCHLUESSEL_DATEI`, then
`schluessel_datei` from the configuration. Whoever sets an environment variable
means it — that is what makes a one-off switch possible without editing a file.

**3 — Point it at your shooting tree.** The source stays untouched; everything is
written into a copy under `ziel`.

**4 — Run it twice.** The second run over the same tree does the same thing as
the first — it skips what is already copied and still enriches it. That is not a
detail: the first version silently did *nothing* on a second run and reported
success.

## Configuration reference

| Field | Meaning | If absent |
|---|---|---|
| `ziel` | destination tree; `~` is expanded | taken from the call |
| `schluessel_datei` | **path to** the key file, never the key | environment variable, if set |
| `modell.anbieter` | `anthropic`, `gemini`, `kimi`, `ollama` | no model is asked |
| `modell.name` | exact model id — you choose, there is no default | — |
| `urheber.name` | written to Creator, Artist, By-line | no authorship written |
| `urheber.stadt` / `.land` | IPTC creator contact | omitted |
| `urheber.email` | creator contact — the machine-readable field | omitted |
| `urheber.website` | `CreatorWorkURL` | omitted |
| `urheber.rechte_url` | `xmpRights:WebStatement` — your licence page | omitted |
| `urheber.nutzungsbedingungen` | `xmpRights:UsageTerms` — your terms in words | omitted |

A file that exists but is **broken** is loud, with its own path in the message. A
typo in your own configuration is the most common error there is, and if it
passed as "no configuration", the tool would appear to run and write nothing.

### How rights are written, and why in that shape

The copyright notice stays **short and readable** — `© 2019 Erika Muster`, with
the year taken from the *exposure*, not from today. Reachability goes into the
IPTC creator-contact fields, and licence wording into `UsageTerms`. This follows
the IPTC Photo Metadata standard rather than convenience: newsrooms, agencies and
image search read the *structured* fields, so a notice stuffed with an address is
tedious for humans and worthless to machines, because nothing parses it.

`xmpRights:Marked` is set as well. Without it the rights status is formally
*unknown*, even with a notice sitting next to it.

The name is written to XMP, IPTC/IIM **and** EXIF. These are three separate
registers in one file and programmes read different ones; setting only
`XMP-dc:Creator` leaves you anonymous in an EXIF viewer.

## Design

The design this implements lives outside this repository (it references the
author's own archive and measurements). The rules that matter here:

- **The unit is the exposure, not the file.** A RAW and its JPEG are one thing.
- **RAW gets a sidecar, JPEG gets it embedded — never both.** Measured, not
  assumed: embedding changes the RAW's bytes, a sidecar leaves it untouched,
  and the sidecar is the form Lightroom, Bridge and Capture One expect.
- **A guess never enters a filename.** An unknown camera model aborts loudly
  rather than inventing an abbreviation, because a wrong one is
  indistinguishable from a right one once written.

## Choosing a model

**You choose.** Provider and model come from configuration, never from the code
(`mkn_kern.modelle`) — Anthropic, Moonshot (Kimi) and a local Ollama model are
equal options, and a local model needs no key and sends nothing anywhere.

There is no built-in default. A default would turn the choice into a prop.

### But there is a measured recommendation

Judging a photo series from its images is a task where a wrong answer is
expensive: it ends up in a **filename**, and once written it is no longer
recognisable as a guess. So the question is not only which model is most often
right, but **which model knows when it is not**.

Measured on 20 cases whose correct answers were fixed *before* any model was
asked, three models, 60 calls:

| Model | Correct | Wrong **and** confident | Precision when it said "certain" |
|---|---|---|---|
| Claude Sonnet 5 | 15/20 | 1 | 12/13 |
| **Claude Opus 5** | **17/20** | **0** | **14/14** |
| Kimi K3 | 16/20 | 3 | 16/19 |

Accuracy is the lesser number. **Calibration is the one that matters**: every
single time Opus called itself certain, it was right. That is what makes its
confidence usable as a gate — and Kimi's is not.

### The rule that follows

> **Only a judgement the model calls certain gets written.** Everything else
> goes on a list for a human to look at; the file keeps its neutral name.

A missing hint costs nothing. A wrong filename costs trust in every other name.

**A second model as a cross-check was tried and rejected.** Letting Opus and
Kimi agree wrote three more cases — and two of them wrong. Two models can agree
and be wrong together; in one case all three were. Requiring both agreement and
confidence gave exactly the same result as confidence alone, at twice the cost.
Cross-checking works when a second party verifies a *claim*; it does not work
when both parties are guessing at the same ambiguous picture.

### Local models

A local model is a legitimate choice and needs no key. Two limits are measured,
not assumed: `gemma4:26b` (18 GB) accepts **one** image at a time, and on a
machine with tight GPU memory it fails outright once an image and a longer
prompt arrive together. That is why series are presented as a **contact sheet** —
several frames rendered into one picture. It is not a convenience; it is what
makes a local model able to answer the question at all.

### Your own notes are read, not transcribed

Where the track says nothing, the tool asks you — a small folder per unanswered
session, a few frames, and a file to write in. **Write anywhere in that file.**

What you write is then *read*, not pattern-matched:

| You wrote | It understands |
|---|---|
| "already the Zugspitze, first frames" | a place: Zugspitze |
| "belongs with the previous folder" | the same place as the session before |
| "somewhere near Mehrwald, I think" | a **guess** — offered back, never written |
| "spontaneous, middle of nowhere" | honestly no place; nothing is invented |
| "it's black, badly exposed" | an exposure flag, and the frame is marked |
| "the time looks wrong to me here" | a doubt about the timestamp, kept for you |

The earlier version searched for keywords. Measured against 20 real notes it
recognised **nine** and discarded the rest — including every "previous folder",
every place named without the magic word, and the exposure remark. A word search
cannot tell "belongs to Grainau" from "on the way back *from* Grainau"; the
difference is in the intent of the sentence, not in its letters.

**A guess is never written.** It comes back on the list instead. A missing hint
costs nothing; a wrong place costs trust in every other one.

### The cheapest step is the one that asks no model

Most series answer themselves. A camera records that it shot an exposure
bracket; that is a fact, not a judgement, and no model should be asked to
second-guess it. Measured on a 1,233-file archive: 626 groups, of which 506 are
single frames and 66 are camera-confirmed brackets. Around 54 groups are left
for a model — which is why the choice of model decides cents, not euros.
