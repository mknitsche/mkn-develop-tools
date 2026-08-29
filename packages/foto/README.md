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

### The cheapest step is the one that asks no model

Most series answer themselves. A camera records that it shot an exposure
bracket; that is a fact, not a judgement, and no model should be asked to
second-guess it. Measured on a 1,233-file archive: 626 groups, of which 506 are
single frames and 66 are camera-confirmed brackets. Around 54 groups are left
for a model — which is why the choice of model decides cents, not euros.
