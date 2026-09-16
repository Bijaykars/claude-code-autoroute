# claude-self-tuning-routing

A `CLAUDE.md` plus eight subagents and three hooks for Claude Code that route work to the cheapest model that can do it, record when a delegated answer turned out wrong, and revert a routing change when the next batch of evidence says it did not help.

Most shared `CLAUDE.md` files are style guides. This one also answers the question "how do you know your routing is right?" with: it measures itself.

## What is inside

| path | what it is |
|---|---|
| `CLAUDE.md` | Global rules: cost routing (know your own tier), token discipline, Karpathy-style "think before coding", the Ponytail ladder, surgical changes, goal-driven execution |
| `agents/locate.md`, `agents/digest.md` | Haiku. Find and read only. Never write code. |
| `agents/scaffold.md`, `agents/implement.md`, `agents/test-writer.md`, `agents/reviewer.md` | Sonnet. Mechanical edits, specified implementation, tests, review. |
| `agents/deep-debug.md` | Sonnet first; escalates itself to Opus only after a reproduction attempt and a ruled-out list. |
| `agents/retune.md` | Reads every agent's ledger and moves tiers one rung at a time, then verifies or reverts its own last move. |
| `hooks/retune-due.py` | SessionStart. Counts ledger rows since each agent's last retune marker and tells the session when retune has enough data. |
| `hooks/prompt-nudge.py` | UserPromptSubmit. Re-asserts "you plan and judge, agents read, search, edit, test" so the rule survives long sessions and compaction. |
| `hooks/inline-counter.py` | PostToolUse. Nudges after N consecutive inline tool calls without delegating. |
| `settings.example.json` | The hook wiring. |

## The routing table

| you are | do yourself | hand off |
|---|---|---|
| Fable / Opus | decide, plan, judge, verdicts, ambiguous or risky edits | all searching, all long reads, boilerplate, well-specified edits, tests, review |
| Sonnet | the above plus well-specified implementation | searching, long reads, boilerplate |
| Haiku | find and read only | never writes code |

Two rules that came from evidence rather than taste:

- **Frontend, UI and design work runs on Opus.** Design Arena website Elo on 2026-09-10: Opus 5 1320, Fable 5.1 1321, Sonnet 5 1289, Haiku 4.5 1135 (third-party mirror of the leaderboard). In September 2026 build-offs Sonnet was described as "consistently third-best and occasionally careless". Opus ties the top model at half the price.
- **Haiku never edits code.** The one exception is a brief that names the file, the exact old text and the exact new text.

## The escalation contract

Every agent that cannot deliver returns exactly this and nothing else:

```
ESCALATE: <one line — why this tier cannot answer it>
TRIED: <what you actually covered>
NEXT: <rescope | effort:<one step up> | model:<next tier>/medium — ONE rung only>
```

The caller re-dispatches to the rung named and no higher. Rescope first, then effort up at the same model, then the next model at medium effort. Nothing jumps straight to the top.

## The self-tuning loop

1. Every agent appends one row to its ledger after each run: `| date | task shape | resolved or escalated | model used |` in `.claude/agent-memory/<agent>/MEMORY.md`.
2. When a delegated result proves wrong (a test fails, a root cause is disproven, an edit has to be redone), the caller appends `| date | task shape | WRONG | model | why |`. Silence reads as success, so this row is the only thing that can ever demote a bad tier.
3. `retune-due.py` fires at session start when an agent has ten or more rows since its last marker.
4. `retune` computes `fail_rate = (escalated + WRONG) / rows`. Promote one rung at `>= 0.40` over ten rows, demote one rung at `<= 0.05` over twenty. Never two rungs. Never below Sonnet for an agent that can write code.
5. Every move writes a marker with its baseline. On the next run retune checks the move first: a promotion that did not cut the fail rate by at least 0.10 is reverted and flagged as "not a tier problem". A demotion that pushed the fail rate above 0.40 is reverted.

## Cost, measured on one working day

Actual subagent token usage from a single session on a real project (a Node/Express trading-signals codebase with a vanilla-JS frontend), 2026-09-14. Twenty-two delegated tasks: repo searches, log digests, a root-cause bug fix, a new UI tab, a review, two research batteries, a theme pass, a web research task.

| tier | tokens | blended $/M (80% in, 20% out) | cost |
|---|---|---|---|
| Haiku 4.5 (locate, digest) | 462k | 1.80 | $0.83 |
| Sonnet 5 (implement, review, debug, research) | 1,725k | 3.60 | $6.21 |
| Opus 5 (UI work) | 275k | 9.00 | $2.48 |
| Fable 5.1 (web research, docs lookup) | 211k | 18.00 | $3.80 |
| **routed total** | **2,673k** | | **$13.32** |
| same tokens, all on Fable 5.1 | 2,673k | 18.00 | $48.12 |

Routed cost is 28% of the all-top-model cost, a 72% saving on the delegated work.

What this does not include: the orchestrating session's own tokens (that is the part Fable was actually paid for), prompt-cache discounts, and the fact that a stronger model might finish in fewer tokens. Treat it as the order of magnitude, not a benchmark. List prices from the Claude API docs on 2026-09-14: Fable 5.1 $10/$50, Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku 4.5 $1/$5 per million input/output tokens.

## Install

1. Copy `CLAUDE.md` to `~/.claude/CLAUDE.md` (or merge with yours; a project `CLAUDE.md` wins on conflict).
2. Copy `agents/*.md` to `~/.claude/agents/`.
3. Copy `hooks/*.py` to `~/.claude/hooks/` and merge `settings.example.json` into `~/.claude/settings.json`. Needs `python` on PATH.
4. Install the Ponytail plugin from its own repo (link below). The ladder in `CLAUDE.md` is a paraphrase; the plugin is the real thing.
5. Start a new session. Ledgers appear under `.claude/agent-memory/` in each project as agents run. Add that path to the project's `.gitignore` if you do not want them committed.

## Status and honesty

- Running on one project since 2026-09-14. The ledgers have a handful of rows. No token saving beyond the table above has been measured.
- The retune thresholds are starting heuristics, and the file says so.
- Agents only write their ledger row if the instruction is explicit and includes the path. The first version did not include the path and nothing was logged.

## Credits

- The "think before coding, simplicity first, surgical changes, goal-driven execution" sections paraphrase [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills), a community distillation of Andrej Karpathy's talk on working with coding agents. Not affiliated with him.
- The ladder paraphrases [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail). Install the plugin for the full behaviour.
- The routing, escalation contract, ledgers, retune loop and hooks are this repo's own.

## License

MIT.
