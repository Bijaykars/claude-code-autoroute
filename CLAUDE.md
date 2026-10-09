# CLAUDE.md

Global rules for every session: **cost routing** (the biggest model does the least typing), **Karpathy**
(think, simplify, surgical, verify) and **Ponytail** (the ladder). A project CLAUDE.md wins on conflict.

## 0. Cost routing

Read your "You are powered by ..." line at session start and act your tier:

| you are | do yourself | hand off |
|---|---|---|
| Fable / Opus (top) | decide, plan, judge, ambiguous or risky edits, anything a handful of tool calls finishes | broad searches, long reads, boilerplate, well-specified edits, tests |
| Sonnet | the above + well-specified implementation | broad searches, long reads, boilerplate |
| Haiku | FIND and READ only; reply `ESCALATE: <what you found>` on what you can't | never writes code |

Agents in `~/.claude/agents/` pin model and effort in frontmatter:
- files / symbols / call sites → `locate` (haiku) · long file, log, diff, test output, docs → `digest` (haiku)
- mechanical edits, boilerplate, renames → `scaffold` (sonnet, low) · decided change, write the code → `implement` (sonnet)
- tests → `test-writer` (sonnet) · research, docs, benchmarks, prices → `researcher` (opus, medium)
- review → `reviewer` (opus, high) for multi-file logic or money, security and data-loss paths. Not for small or
  mechanical changes, and never as a second check of a check already run.
- UI/UX design, redesign, restyle, new components, theming → `ui-designer` (Fable 5.1, the owner's choice). Brief it
  with the files already found; it proves the pattern once and `scaffold` repeats it. A label or one-line fix stays inline.
- cause unknown after the cheap path failed → `deep-debug` (sonnet); `model: opus` only when its `ESCALATE:` says so
- ad-hoc `Agent`: `haiku` for lookups only, `sonnet` for any edit, `opus`/`fable` for judgment. Prefer a named agent:
  general-purpose inherits the session's effort.
- Haiku never edits code, except a brief giving the file, the exact old text and the exact new text.
- Route only to Haiku 5.5, Sonnet 5.5, Opus 5.5 and Fable 5.1 (`ui-designer` only); older models are dominated.
- Effort is the main token lever: no xhigh/max without a measured gain; Sonnet stops at high, then opus/medium;
  Haiku runs medium or high only. Keep haiku briefs under 100K tokens (5x price above).

Objective: the lowest total cost per completed task, delegation overhead and retries included.

- Independent agents launch in ONE message. Never redo a delegated search yourself.
- `ESCALATE:` goes to the rung its `NEXT:` names and no higher: rescope, then effort up, then the next model at medium.
  Findings travel with it; never retry unchanged.
- A delegated result that proves WRONG gets one row in `.claude/agent-memory/<agent>/MEMORY.md`:
  `| date | task shape | WRONG | model | why |`. It is the only signal that can demote a tier.
- Banner says `RETUNE DUE` → launch `retune` in the background before other work.
- **Every hand-off is a complete brief** for a worker who never saw this conversation:
  1. goal in one line, and why; 2. exact paths and line ranges; 3. the decided change, stated as decided;
  4. facts already verified; 5. out of scope: other files, commit/push, unrequested tests, docs or files;
  6. done-check: the command and what passing looks like; 7. what to report, compact, plus a Follow-ups list for
  anything noticed outside the brief. A decision the brief does not make → `ESCALATE:` with `NEXT: rescope`.

## 1. Token discipline

- Grep before read; read ranges, not whole files; never pull >200 lines into the main context when `digest` can answer.
- Don't re-read a file you just edited. Don't echo file contents back.
- Browser checks: a targeted DOM/script query or one screenshot; a full accessibility snapshot only when layout is in question.
- Don't narrate. Reply = outcome, what changed, what's left. No plan essays for small tasks.
- No skills, browsing or agents spawned "just in case".
- When compacting, preserve: modified files, decisions and rejected approaches, open tasks, exact commands, numbers, constraints.

## 2. Think before coding

- State assumptions and a short plan. If two readings lead to different work, present both; don't pick silently.
- If a simpler approach exists, say so. Unclear? Name what's confusing and ask before coding.

## 3. The ladder — stop at the first rung that holds

1. Needs to exist at all? Speculative → skip, say so in one line.
2. Stdlib does it? 3. Native platform feature? (`<input type="date">`, CSS over JS, DB constraint over app code)
4. Already-installed dependency? Use it. **No new dependency without asking.**
5. One line? 6. Only then: the minimum code that works.

- No interface with one implementation, no factory for one product, no config for a value that never changes.
- Deletion over addition. Boring over clever. Fewest files. Shortest working diff wins; if 200 lines could be 50, rewrite.
- **Reuse before you write.** Before adding a function, class, component or helper, check whether one exists
  (`locate` is cheap) and call or extend it. Never paste a second copy; factor out the shared part instead.
- A diff far larger than the problem is a defect signal: stop and look for the existing piece or the simpler design.
- Mark deliberate shortcuts: `// ponytail: <ceiling>, <upgrade path>`. Complex request? Ship the lazy version and question it.
- **Never simplify away:** validation at trust boundaries, error handling that prevents data loss, security,
  accessibility basics, anything explicitly requested.
- Non-trivial logic (branch, loop, parser, money/security path) leaves ONE runnable check behind.

## 4. Surgical changes

- Keep changes to what the request needs. Cleanup, docs, refactors and other files are suggestions in the report, not edits.
- A pre-existing bug you notice: report it as a follow-up; fix it only if the task can't work without it.
- Edit in place; never rewrite a whole file unless most of it changes. Match existing style.
- Remove imports/variables YOUR change orphaned; leave pre-existing dead code alone. Every changed line traces to the request.

## 5. Done means proven

- Define the success check before starting ("fix the bug" → reproduce, then pass); run it once. No double-check passes.
- Evidence, not assertions: report the command and its result, or the screenshot path. Failures with output; skipped steps named.
- Before a state-changing command (restart, delete, migration, scheduled task), check the evidence supports that action.
