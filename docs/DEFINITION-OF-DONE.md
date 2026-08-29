# Definition of Done

A change is done when every point below is true **and was checked**, not when it
looks finished. The order matters: this is read *before* the first line of code,
not after the last.

## 1. The problem was stated before the solution

There is a written problem statement, and it survived contact with the code. If
the problem turned out to be different, the statement was corrected — not
quietly abandoned.

## 2. Tests exist and they proved something

- The behaviour is covered by a test that **fails without the change**.
- **Every new assertion was made red by a mutation.** Break the code the test
  guards; if the test stays green, it guards nothing and does not count. This is
  not a formality — it is the only thing that distinguishes a test from a
  comment. It has already found a hollow guard in this repository on day one.
- Assertions are on **behaviour**, not on wording. Matching log text or source
  strings tests the spelling.
- Every exclusion has a **lower bound**: "nothing unexpected found" over an empty
  set is trivially true. Show that there was something to find.
- Conditions the test depends on (read-only paths, permissions, absent tools,
  time zone) are **established by the test**, not assumed from the machine.

## 3. It runs where the users are

Tests pass on Linux, macOS and Windows, on every supported Python version. A
platform-specific shortcut is a defect, not a detail — the CI matrix is the
proof, not the intention.

## 4. No hidden dependency crept in

No database, no tunnel, no account, no provider key is needed to build or test.
If a model is used, the provider comes from configuration and the code path is
tested without one.

## 5. The evidence is written down

The pull request states **what was run and what came back** — the command and
the outcome, not a summary of a feeling. "Should work" is not evidence.

Proof runs count on the **final state**. If anything was changed after the run,
the run happened on a state that no longer exists and has to be repeated.

## 6. What was touched is complete

- No half-repairs. A partial fix is worse than none because it looks handled.
- Something unrelated found along the way is **reported, not repaired in
  passing**. A drive-by fix makes a change unreviewable and hides its own risk.
- If the change grew beyond its original shape — a second area, a second
  concern, more than one commit's worth — it stopped being small at that moment.
  Split it.

## 7. The documentation caught up in the same change

If the change altered how something is used, configured or operated, the text
that describes it changed with it — in the same commit, not in a follow-up that
never comes.

## 8. It is public-ready

This repository is public. Before pushing:

- No credential, key, token or personal data — not in the diff, not in a
  fixture, not in a test name.
- Nothing that identifies a private individual.
- The commit message reads for a stranger a year from now: **why**, not what the
  diff already shows.
