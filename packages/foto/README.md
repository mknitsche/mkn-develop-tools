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
