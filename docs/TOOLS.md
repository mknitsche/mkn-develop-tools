# Tools in this repository

One page that answers three questions for every tool: what is it for, how do I
call it, and where does it stand. Details live in each package's own README;
the version history lives in each package's `CHANGELOG.md` and on the
[releases page](https://github.com/mknitsche/mkn-develop-tools/releases).
Version numbers are deliberately not repeated here — a copied number is the
first thing that goes stale.

Get all of them from a clone of this repository:

```bash
git clone https://github.com/mknitsche/mkn-develop-tools
cd mkn-develop-tools
uv sync --all-packages      # installs every package and its commands into .venv
uv run mkn-dokument --help
```

## Overview

| Package | Purpose | Commands | State |
|---|---|---|---|
| [`mkn-dokument`](../packages/dokument/README.md) | Read documents you cannot afford to misread | `mkn-dokument lesen`, `seiten`, `ablesen`, `epub`, `deckblatt` | released, in daily use |
| [`mkn-audio`](../packages/audio/README.md) | Turn a document into an audio file with chapters | `mkn-mp4-local`, `mkn-mp4-gemini` | released, in use |
| [`mkn-foto`](../packages/foto/README.md) | Enrich photos with place, series and keywords | `mkn-foto` | released, in use |
| [`mkn-kern`](../packages/kern/README.md) | Shared foundation of the packages above | library only | released |

## mkn-dokument — read documents

**For:** PDFs with or without a text layer, scans and photos whose values go
into a database without anyone checking every number.

**How it works:** every page is read from the image by two models of different
providers. A program without a model compares the two readings; only what both
read alike is taken over, everything else goes to a review list with a reason.

| Command | Reads | Result |
|---|---|---|
| `mkn-dokument lesen` | printed values: table rows, header fields, labelled numbers | `ergebnis.json` |
| `mkn-dokument seiten` | per page: kind, issuer, date, running text, list of charts | `seiten.json` |
| `mkn-dokument ablesen` | marked points of a chart that prints no numbers | `ablesung.json` |
| `mkn-dokument epub` | an EPUB without any model: metadata, ISBN, chapters | JSON on stdout |
| `mkn-dokument deckblatt` | no model: `setzen` puts a cover sheet in front of a PDF, `abnehmen` takes it off again, `lesen` returns what it states | a new PDF, or JSON on stdout |

As a library, `mkn_dokument.epub` additionally returns the full text in reading
order and the linked notes of a book, each at the paragraph that cites it. Copy
protection is detected and refused, never circumvented.

The cover sheet is one inserted first page; bookmarks, links and attachments of
the source stay as they are, an existing target is never overwritten, and signed
PDFs are refused. Taking it off works only on a sheet this tool has set.

**Needs:** keys for two model providers of your choice (not for `epub` and `deckblatt`).

## mkn-audio — make documents listenable

**For:** listening to a book, a paper or a long text instead of reading it.

**How it works:** a source (EPUB, PDF, text, photo or screenshot) becomes an
`.m4b` with chapter marks, title, author and cover, or one MP3 per chapter.
A report next to the file states what was not read, left out or not spoken
cleanly.

| Command | Voice |
|---|---|
| `mkn-mp4-local` | a voice model running on your own machine |
| `mkn-mp4-gemini` | a hosted voice; asks before sending a source that looks personal |

**Needs:** `ffmpeg` on `PATH`; for the hosted voice a provider key.

## mkn-foto — enrich photos

**For:** a photo archive in which place, series and keywords travel inside the
image files rather than in one program's database.

**How it works:** reads a shooting tree, recognises series, resolves places from
a GPS track and writes the result back into RAW and JPEG files. The source
folder stays untouched: `mkn-foto <folder>`; `mkn-foto --help` lists the options.

**Needs:** ExifTool on `PATH`; a model provider only for the optional keyword
step.

## mkn-kern — shared foundation

Provider choice and model request shared by the other packages. Deliberately
small: no provider client, no database handle, nothing that assumes anyone's
infrastructure. You do not install it on its own.

## What is not here

Tools that maintain the author's personal assistant — its database, its
sessions, its filing — stay private (see the dividing line in the
[README](../README.md)). A tool moves here once it stands on its own.
