# AutoRoute for Claude Code

Cost-aware subagent routing for Claude Code, with failure tracking and experimental self-tuning.

Let cheaper models handle routine work, and escalate when they struggle.

## The problem

If you run Claude Code on the most capable model, that model also does your file searches, reads your logs, writes your boilerplate and runs your tests. Those tasks do not need it. Subagents can run on cheaper models, but hand-written routing rules go stale, and nothing tells you when a cheap model has been quietly giving wrong answers.

## What AutoRoute does

- **Routes by tier.** The session reads which model it is and hands work down: Haiku finds and reads, Sonnet implements, tests and reviews, Opus does UI, the top model only decides.
- **Escalates one rung at a time.** An agent that cannot deliver returns a fixed `ESCALATE` block naming the next rung. Nothing jumps straight to the top model.
- **Records failures.** Every agent logs a ledger row. When a delegated answer proves wrong, the caller logs a `WRONG` row. Silence would otherwise read as success.
- **Tunes itself, and reverts.** A `retune` agent moves tiers one rung at a time from those ledgers, then checks its own last move against its baseline and reverts it if the next window did not improve.

## Quick install

```bash
git clone https://github.com/Bijaykars/claude-code-autoroute
cd claude-code-autoroute
python install.py            # --dry-run to preview, --uninstall to remove
```

`install.py` (stdlib only, Python 3.9+) copies the agents and hooks into `~/.claude/`, merges the
three hook entries into `~/.claude/settings.json`, and installs `CLAUDE.md`: a full copy if you have
none yet, or just section 0 ("Cost routing") appended inside `<!-- autoroute:start -->` /
`<!-- autoroute:end -->` markers if you already have your own — your other rules are never touched.
It backs up anything it would overwrite to `<file>.bak-<timestamp>` first, and `--uninstall` restores
those backups.

Then install the [Ponytail plugin](https://github.com/DietrichGebert/ponytail) from its own repo and
start a new session. Ledgers appear under `.claude/agent-memory/<agent>/` in each project as agents
run; git-ignore that path if you do not want them committed.

Prefer to do it by hand? The manual equivalent:

```bash
cp agents/*.md ~/.claude/agents/
mkdir -p ~/.claude/hooks && cp hooks/*.py ~/.claude/hooks/
# then merge settings.example.json into ~/.claude/settings.json,
# and merge CLAUDE.md's section 0 into your own CLAUDE.md by hand
```

## One real task

A nightly job wrote ranks `1, 2, 3, 5` and a test that asserts contiguous ranks failed. Cause unknown.

1. The session (top model) did not open the file. It briefed `deep-debug`, which runs on Sonnet.
2. `deep-debug` queried the table read-only, read the writer, and found the rank was assigned from the array index before a minimum-history filter dropped a freshly listed name. It replaced the index with a per-side counter that only advances on rows actually written, re-ran the single test, then the suite.
3. It returned the mechanism with file and line, the fix, and a green test count. It appended `| date | rank gap in nightly writer | resolved | sonnet |` to its ledger.

No Opus or top-model tokens were spent on the investigation. Had Sonnet been stuck, the reply would have been an `ESCALATE` block with the ruled-out list attached, and the same agent would have been re-run on Opus from that list rather than from zero.

## When not to delegate

Starting an agent has overhead. A one-line edit in a file already open, or a single grep, is faster inline, and Anthropic's own guidance says quick, targeted changes suit the main conversation. `CLAUDE.md` says the same. The `inline-counter.py` hook nudges after four consecutive inline tool calls by default; raise `DELEGATE_TRIPWIRE` in your settings `env` block if that is too eager for your work.

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

The caller re-dispatches to the rung named and no higher. Rescope first, then effort up at the same model, then the next model at medium effort.

## The self-tuning loop

1. Every agent appends one row to its ledger after each run: `| date | task shape | resolved or escalated | model used |` in `.claude/agent-memory/<agent>/MEMORY.md`.
2. When a delegated result proves wrong (a test fails, a root cause is disproven, an edit has to be redone), the caller appends `| date | task shape | WRONG | model | why |`.
3. `retune-due.py` fires at session start when an agent has ten or more rows since its last marker.
4. `retune` computes `fail_rate = (escalated + WRONG) / rows`. Promote one rung at `>= 0.40` over ten rows, demote one rung at `<= 0.05` over twenty. Never two rungs. Never below Sonnet for an agent that can write code. It edits the agent file where it is actually installed: `~/.claude/agents/<name>.md` by default, or the project's `.claude/agents/<name>.md` when a project-level copy overrides it.
5. Every move writes a marker with its baseline. On the next run retune checks the move first: a promotion that did not cut the fail rate by at least 0.10 is reverted and flagged as "not a tier problem". A demotion that pushed the fail rate above 0.40 is reverted.

## Cost, in theory

List prices per million tokens from the Claude API docs (2026-09-14): Fable 5.1 $10 in / $50 out, Opus 5 $5 / $25, Sonnet 5 $2 / $10, Haiku 4.5 $1 / $5. At an 80/20 input/output mix that is a blended $18 / $9 / $3.60 / $1.80 per million, so Opus is half of Fable, Sonnet a fifth, Haiku a tenth.

The saving depends entirely on how much of a session is lookup and mechanical work versus judgment. An illustrative split for a typical coding session, 1M delegated tokens:

| share of tokens | kind of work | runs on | blended $/M | cost |
|---|---|---|---|---|
| 30% | searching, reading logs and docs | Haiku | 1.80 | $0.54 |
| 50% | specified edits, tests, review, scripts | Sonnet | 3.60 | $1.80 |
| 15% | UI and design | Opus | 9.00 | $1.35 |
| 5% | judgment, verdicts | Fable | 18.00 | $0.90 |
| **100%** | | **routed** | | **$4.59** |
| 100% | everything on the top model | Fable | 18.00 | $18.00 |

Under that split the delegated work costs about a quarter of the all-top-model price. Move the split toward judgment and the saving shrinks; move it toward lookups and it grows. Measure your own split from the ledgers before quoting a number, and remember the orchestrating session itself still runs on the top model. Subscription usage is a different accounting from API cost; keep them separate.

### Estimated API cost from reported token usage, one working day

One session on the author's own project (a Node/Express trading-signals codebase with a vanilla-JS frontend), 2026-09-14, using the token counts each subagent reported on completion. Twenty-two delegated tasks: repo searches, log digests, a root-cause bug fix, a new UI tab, a code review, two research batteries, a theme pass, a web research task. The dollar figures assume an 80/20 input/output split because the reported counts were totals, not separate input/output/cache numbers; real input/output/cache accounting is on the roadmap.

| tier | tokens | blended $/M (80% in, 20% out) | cost |
|---|---|---|---|
| Haiku 4.5 (locate, digest) | 462k | 1.80 | $0.83 |
| Sonnet 5 (implement, review, debug, research scripts) | 1,725k | 3.60 | $6.21 |
| Opus 5 (UI work) | 275k | 9.00 | $2.48 |
| Fable 5.1 (web research, docs lookup) | 211k | 18.00 | $3.80 |
| **routed total** | **2,673k** | | **$13.32** |
| same tokens, all on Fable 5.1 | 2,673k | 18.00 | $48.12 |

The delegated work cost 28% of what the same tokens would have cost on the top model. The split that day was 17% Haiku, 65% Sonnet, 10% Opus, 8% Fable by tokens, so it was heavier on Sonnet than the illustrative split above and lighter on lookups.

What it excludes: the orchestrating session's own tokens (the part the top model was actually paid for), prompt-cache discounts, retries, and the possibility that a stronger model would have finished some tasks in fewer tokens. One day, one project, one operator. It is the order of magnitude, not a benchmark; the reproducible comparison is on the roadmap.

## What is inside

| path | what it is |
|---|---|
| `CLAUDE.md` | Global rules: cost routing (know your own tier), token discipline, Karpathy-style "think before coding", the Ponytail ladder, surgical changes, goal-driven execution |
| `agents/locate.md`, `agents/digest.md` | Haiku. Find and read only. Never write code. |
| `agents/scaffold.md`, `agents/implement.md`, `agents/test-writer.md`, `agents/reviewer.md` | Sonnet. Mechanical edits, specified implementation, tests, review. |
| `agents/deep-debug.md` | Sonnet first; escalates itself to Opus only after a reproduction attempt and a ruled-out list. |
| `agents/retune.md` | Reads every agent's ledger and moves tiers one rung at a time, then verifies or reverts its own last move. |
| `hooks/retune-due.py` | SessionStart. Counts ledger rows since each agent's last retune marker and says when retune has enough data. |
| `hooks/prompt-nudge.py` | UserPromptSubmit. Re-asserts "you plan and judge, agents read, search, edit, test" so the rule survives long sessions and compaction. |
| `hooks/inline-counter.py` | PostToolUse. Nudges after N consecutive inline tool calls without delegating. |
| `settings.example.json` | The hook wiring. |

## Status and honesty

- Running on one project since 2026-09-14. The ledgers have a handful of rows. One working day has been measured (table above); the illustrative split is theory. Neither is a benchmark.
- The retune thresholds are starting heuristics, and the file says so.
- Agents only write their ledger row if the instruction is explicit and includes the path. The first version did not include the path and nothing was logged.

## Roadmap

- Package the agents and hooks as a Claude Code plugin with install verification and clean uninstall, so users keep their own `CLAUDE.md`.
- A small reproducible comparison: ordinary Claude Code, fixed model assignments, routing with retuning. Task success, total cost including the main session and delegation overhead, elapsed time, retries.
- Short documentation pages: setup and actual behaviour; whether routing saves money, with limits; how failed delegations are escalated, tuned and rolled back.
- `/autoroute status | explain | off | rollback` commands.
- An automatic SubagentStop-hook ledger writer, shipped with an "unverified until evidence" status.

## Credits

- The "think before coding, simplicity first, surgical changes, goal-driven execution" sections paraphrase [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills), a community distillation of Andrej Karpathy's talk on working with coding agents. Not affiliated with him.
- The ladder paraphrases [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail). Install the plugin for the full behaviour.
- The routing, escalation contract, ledgers, retune loop and hooks are this repo's own.

## License

MIT.
