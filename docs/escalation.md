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
2. **effort up** at the current model (low → medium → high → xhigh).
3. **next model** at medium effort (haiku → sonnet → opus). Never jump straight
   to opus from haiku.

## The one-rung rule

An agent's `NEXT:` may only name the rung immediately above its own on the
9-rung ladder used by `retune` (`agents/retune.md`):

```
1  haiku  / low
2  haiku  / medium
3  haiku  / high
4  sonnet / low
5  sonnet / medium
6  sonnet / high
7  sonnet / xhigh
8  opus   / high
9  opus   / xhigh
```

The caller re-dispatches to exactly that rung — it may not jump further on its
own judgment, even if it suspects the escalation will fail again. Findings
travel with the re-dispatch; the next attempt never starts from zero.

## Haiku never edits code

The only exception: a brief that names the file, the exact old text and the
exact new text — a find-and-replace, not a task. Anything that requires a
decision about the code goes to sonnet or above, so a haiku agent facing that
kind of request escalates rather than guessing.
