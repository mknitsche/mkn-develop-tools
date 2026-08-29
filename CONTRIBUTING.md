# Contributing

Thank you for looking. This is a small project with a high bar; the bar is about
evidence, not ceremony.

## Before you write code

Open an issue describing **the problem**, not the patch you have in mind. Most
disagreements are about the problem statement, and finding that out after the
code is written wastes your time more than mine.

## The quality bar

These are the rules the maintainer holds himself to. They apply to pull requests
in the same way.

1. **Tests first.** New behaviour arrives with a test that fails without it.
2. **A test counts as proof only once a mutation has made it fail.** A green
   test proves something about the test run, not about the code. If you cannot
   break your own test by breaking the code it guards, it is not guarding
   anything.
3. **A test asserts on behaviour, not on wording.** Matching on log text or
   source strings tests the spelling and breaks on the next rename.
4. **An exclusion needs a lower bound.** "Nothing unexpected was found" is
   trivially true over an empty set. Show that there was something to find.
5. **State what you actually ran.** Paste the command and the outcome. "Should
   work" is not an outcome.
6. **Finish what you touch.** A partial fix is worse than none — it looks
   handled. If the change grows beyond its original shape, say so and split it.
7. **Found something else?** Report it, do not repair it in passing. A drive-by
   fix in an unrelated area makes a pull request unreviewable.

## Developer Certificate of Origin

Contributions are accepted under the **Developer Certificate of Origin 1.1**
(<https://developercertificate.org/>). It is a statement that you wrote the
contribution, or have the right to submit it, and that you are content for it to
be distributed under this project's licence.

Sign off each commit:

```
git commit -s -m "your message"
```

which appends:

```
Signed-off-by: Your Name <your.email@example.com>
```

Use your real name. There is no separate copyright assignment: **you keep the
copyright in your contribution** and license it to the project under the AGPL-3.0.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`,
with `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Write the body for
someone reading it in a year without the context you have today — say **why**,
not what the diff already shows.

## Language

Public-facing documents (this file, `README.md`, `SECURITY.md`, code comments,
commit messages) are in **English**, so that anyone can read them. The author's
own design notes may be in German; that never applies to anything a contributor
needs in order to take part.

## Who decides what goes in

This project is owned and maintained by Matthias Nitsche. **Contributions are
welcome; integration and releases are not delegated.** Every merge into `main`
and every release is the maintainer's decision — there is no path by which a
change enters this project without that decision.

That is a statement of governance, not of distrust: a single owner means a
single place where responsibility sits, and you always know who answered you and
why. It also means review may take a while — see below.

## What you can expect

A response, and a reason. If a pull request is declined, you get the argument
that decided it — not silence.
