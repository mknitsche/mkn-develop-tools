# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Repository established, public from the first commit.
- Governance: licence (AGPL-3.0), NOTICE with trademark reservation,
  contribution terms under the Developer Certificate of Origin, security policy,
  code of conduct.
- Apparatus: local guard rails (hygiene, ruff, gitleaks, conventional commits),
  CI, and a Definition of Done whose first rule is the chain
  problem -> solution -> test.
- `mkn-foto`: one configuration file (`~/.config/mkn-foto/konfig.json`, or
  `MKN_FOTO_KONFIG`) holding destination, key-file location, model choice and
  authorship. The software knows the *place* of a key, never the key.
- `mkn-foto`: authorship, contact and rights are written to every image
  following the IPTC Photo Metadata standard -- a short copyright notice
  carrying the *exposure's* year, reachability in the creator-contact fields,
  and an explicit `xmpRights:Marked`.
- Getting-started guide and a configuration reference in the package README.
- `mkn-foto`: handwritten answers are now **read**, not transcribed. A model
  interprets each note, so "the previous folder", "already the Zugspitze" and
  "it's black, badly exposed" carry the meaning they obviously have. Measured
  against 20 real notes: keyword matching recognised nine of them.
- Every written file records **which build wrote it** (`xmp:CreatorTool`).
  Without it, a tree assembled over several runs cannot be told apart, and the
  only safe answer is to delete it and start over. That is exactly what
  happened on 2026-08-30.
- Automated versioning (release-please): versions move from the commits, not by
  hand, and both places that carry a version stay in step.

### Fixed
- `mkn-foto`: a second run over the same destination tree used to do nothing
  and report success. Files already copied were counted as skipped but not
  handed to the enrichment step, so it received an empty mapping.
