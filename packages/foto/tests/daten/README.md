# Test data

## `serien_grundwahrheit.json`

Hand-made ground truth for series recognition: eleven groups of consecutive
frames, each judged by looking at a contact sheet of five frames side by side.

**Why this file exists.** Deciding whether five near-identical frames are a
panorama, a burst, or nothing at all cannot be derived from metadata — the
camera does not record it. Someone has to look. That looking took an afternoon,
and without this file it would have to be done again.

**Why the exposure brackets are not in here.** The camera records them itself
(`AutoBracketing`, sequence number, EV steps). A hand judgement would be worse
than the source, and inviting one would mean asking a model to second-guess a
fact.

**Three groups are labelled `mehrdeutig`** — genuinely undecidable, one of them
a pan that goes out and comes back. They are recorded rather than forced into a
class, and they must not be scored. An ambiguous case with an invented truth
measures nothing; it only produces a number.

**`blind_beurteilt: false` matters.** Three groups were judged *after* model
answers for them were already known. That is the direction in which a
measurement quietly corrupts itself, so it is marked rather than hidden. Those
three must not decide a model comparison.

**Paths are relative** to the shooting tree, not absolute: the archive is
personal and does not live in this repository. A test that wants to use this
file has to be given the archive root and must skip cleanly when it is absent.

There is deliberately **no test on this file yet.** It describes an expectation
for a component that does not exist — series recognition arrives in a later
step, and its test arrives with it. A test that only checked this file's shape
would guard nothing.
