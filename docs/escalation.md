# Escalation contract

See also: [install.md](install.md) (setup) · [self-tuning.md](self-tuning.md) (the retune loop that reads escalations).

Every agent that cannot deliver returns exactly this and nothing else:

```
ESCALATE: <one line — why this tier cannot answer it>
TRIED: <what you actually covered>
NEXT: <rescope | effort:<one step up> | model:<next tier>/medium — ONE rung only>
```

The caller re-dispatches to the rung named in `NEXT:` and no higher.

## Rung order

Rescope first, then effort up at the same model, then the next model at
medium effort:

1. **rescope** — a narrower or better-specified ask at the same tier.
2. **effort up** at the current model. Haiku: medium → high (never low, which skips searches, or xhigh, which can end a turn with no text). Sonnet: low → medium → high. Opus: medium → high → xhigh → max.
3. **next model** (haiku → sonnet → opus): a haiku agent names sonnet/medium, a
   sonnet agent names opus/medium. Never jump straight to opus from haiku.

## The one-rung rule

An agent's `NEXT:` may only name the rung immediately above its own on the
9-rung ladder used by `retune` (`agents/retune.md`):

```
1  haiku  / medium   (find/read agents only)
2  haiku  / high     (find/read agents only)
3  sonnet / low
4  sonnet / medium
5  sonnet / high
6  opus   / medium
7  opus   / high
8  opus   / xhigh
9  opus   / max
```

The haiku rungs serve find/read agents only (`locate`, `digest`). Code-writing agents keep the sonnet/low floor and never move onto a haiku rung.

The caller re-dispatches to exactly that rung — it may not jump further on its
own judgment, even if it suspects the escalation will fail again. Findings
travel with the re-dispatch; the next attempt never starts from zero.

One documented exception: `deep-debug` starts at sonnet/high (rung 5) and names opus/high (rung 7) directly. A bug that has already survived a reproduction attempt and a ruled-out list is constrained by model capability rather than effort, so the intermediate opus/medium rung mostly buys a second identical dead end. Every other agent obeys the one-rung rule.

## Haiku never edits code

The only exception: a brief that names the file, the exact old text and the
exact new text — a find-and-replace, not a task. Anything that requires a
decision about the code goes to sonnet or above, so a haiku agent facing that
kind of request escalates rather than guessing.
