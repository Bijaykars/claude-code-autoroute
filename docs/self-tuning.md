# Self-tuning loop

See also: [install.md](install.md) (setup) · [plugin.md](plugin.md) (the plugin path and the hook-captured ledger) · [escalation.md](escalation.md) (the ESCALATE contract these ledgers record).

## Two ledgers, one primary (since 0.3)

There are now two sources of the same evidence, kept side by side:

- **`.claude/autoroute/ledger.jsonl`** — hook-captured, written automatically by
  `hooks/ledger.py` on every delegation (`PreToolUse(Agent)` →
  `SubagentStart` → `SubagentStop`). No agent cooperation required, so it
  cannot be skipped by a run that forgot to write its row. This is the
  PRIMARY source once it has rows: `retune-due.py` and `agents/retune.md` both
  prefer it over MEMORY.md, per agent, whichever has more rows.
- **`.claude/agent-memory/<agent>/MEMORY.md`** — agent-written, the original
  mechanism (below). Still required this release; not being removed yet. It
  remains the fallback for a project, or an agent, where the JSONL ledger has
  no rows.

A delegated result proving wrong is now recorded with `python autoroute.py
wrong <agent_id|last> "<why>"`, which appends a `wrong` event to the JSONL
ledger — this replaces (but does not yet remove) hand-writing a `WRONG` row in
MEMORY.md.

1. Every agent appends one row to its ledger after each run: `| date | task
   shape | resolved or escalated | model used |` in
   `.claude/agent-memory/<agent>/MEMORY.md`.
2. When a delegated result proves wrong (a test fails, a root cause is
   disproven, an edit has to be redone), the caller appends `| date | task
   shape | WRONG | model | why |` — or, since 0.3, runs `python autoroute.py
   wrong <agent_id|last> "<why>"`.
3. `retune-due.py` fires at session start when an agent has ten or more rows
   since its last marker, checking both ledgers and reporting whichever has
   more rows.
4. `retune` computes `fail_rate = (escalated + WRONG) / rows`. Promote one
   rung at `>= 0.40` over ten rows, demote one rung at `<= 0.05` over twenty.
   Never two rungs at once. Never below Sonnet for an agent that can write
   code. It edits the agent file where it is actually installed:
   `~/.claude/agents/<name>.md` by default, or the project's
   `.claude/agents/<name>.md` when a project-level copy overrides it — writing
   a project-level override rather than editing the global file means evidence
   gathered in one project never silently changes routing in every other
   project.
5. Every move writes a marker with its baseline. On the next run, retune
   checks the move first: a promotion that did not cut the fail rate by at
   least 0.10 is reverted and flagged as "not a tier problem". A demotion that
   pushed the fail rate above 0.40 is reverted.

Full mechanics — the ledger row format, the marker line, the never-demote
list, and what gets flagged for a human rather than acted on — live in
`agents/retune.md`.

## Example

A nightly job wrote ranks `1, 2, 3, 5` and a test that asserts contiguous
ranks failed. Cause unknown.

1. The session (top model) did not open the file. It briefed `deep-debug`,
   which runs on Sonnet.
2. `deep-debug` queried the table read-only, read the writer, and found the
   rank was assigned from the array index before a minimum-history filter
   dropped a freshly listed name. It replaced the index with a per-side
   counter that only advances on rows actually written, re-ran the single
   test, then the suite.
3. It returned the mechanism with file and line, the fix, and a green test
   count. It appended `| date | rank gap in nightly writer | resolved |
   sonnet |` to its ledger.

No Opus or top-model tokens were spent on the investigation. Had Sonnet been
stuck, the reply would have been an `ESCALATE` block with the ruled-out list
attached, and the same agent would have been re-run on Opus from that list
rather than from zero.
