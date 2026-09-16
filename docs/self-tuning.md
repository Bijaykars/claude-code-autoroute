# Self-tuning loop

See also: [install.md](install.md) (setup) · [escalation.md](escalation.md) (the ESCALATE contract these ledgers record).

1. Every agent appends one row to its ledger after each run: `| date | task
   shape | resolved or escalated | model used |` in
   `.claude/agent-memory/<agent>/MEMORY.md`.
2. When a delegated result proves wrong (a test fails, a root cause is
   disproven, an edit has to be redone), the caller appends `| date | task
   shape | WRONG | model | why |`.
3. `retune-due.py` fires at session start when an agent has ten or more rows
   since its last marker.
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
