# mkn-develop-tools

Standalone tools by **Matthias Nitsche** — built in the open, model-agnostic,
and usable without any of the author's own infrastructure.

> **Why this repository is public from day one.** Working in the open is a
> discipline, not a publishing step at the end. Every commit here is written on
> the assumption that anyone may read it. That assumption changes how things get
> built — and it is the reason this repository was public before it contained a
> single line of application code.

## What belongs here — and what does not

The dividing line is **belonging**, not technology:

| Question | Repository |
|---|---|
| Is it part of the author's personal knowledge assistant? | private `claudeAI` |
| Is it a **tool** that stands on its own? | **here** |

A tool may well use a language model — that does not make it part of the
assistant. Conversely, anything that maintains the assistant's own database or
sessions stays private, even if it would run standalone.

## Principles

1. **Model-agnostic.** Where a tool uses a language model, the user chooses the
   provider. Provider and credentials come from configuration, never from code.
   No provider is hard-coded, and no provider is required to build or test.
2. **No hidden infrastructure.** Nothing here needs a database, an SSH tunnel or
   an account belonging to the author. If a test needs a service, it ships the
   service or it does not run in CI.
3. **Cross-platform by default.** macOS is where this is developed; it is not a
   requirement. Platform-specific shortcuts get replaced by portable ones.
4. **Evidence over assertion.** A change is done when something was run and the
   output was read — not when it looks right.

## Packages

The repository is a monorepo. Each package is a self-contained domain; the
shared apparatus (linting, tests, CI, release) exists once for all of them.

| Package | Purpose | Status |
|---|---|---|
| `packages/kern` | shared foundation used by the other packages | scaffolding |
| `packages/foto` | photo workflow tools (import, enrichment) | planned |

## Licence and intellectual property

This project is licensed under the **GNU Affero General Public License v3.0** —
see [LICENSE](LICENSE).

What that means in practice:

- **You may** read, run, study, modify and redistribute this software.
- **You must** keep it under the same licence, state your changes, and preserve
  the copyright and [NOTICE](NOTICE).
- **You may not** take this work into a closed product. If you run a modified
  version as a network service, its source must be offered to its users.
- **Names and logos are not licensed.** See [NOTICE](NOTICE).

The copyright remains with the author. Contributions are accepted under the
Developer Certificate of Origin — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

Issues and pull requests are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) first — it is short, and it describes the
quality bar rather than a formatting ritual.

Security reports do **not** belong in public issues; see
[SECURITY.md](SECURITY.md).
