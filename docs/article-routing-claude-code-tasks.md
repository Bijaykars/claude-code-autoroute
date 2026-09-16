<!-- Draft for external publication; not rendered in the repo docs index. -->

# Routing Claude Code tasks between Haiku, Sonnet, and Opus

I run Claude Code on a Node/Express trading-signals project, and for a while my top-tier session did everything: grepping for a function, reading a 400-line log, writing a boilerplate test, and also making the calls that actually needed judgment. All of that ran at the same rate, because it was all the same model. Nothing told me when a cheaper model would have been fine, and nothing told me when a delegated answer was quietly wrong.

That is the gap I built AutoRoute to close: https://github.com/Bijaykars/claude-code-autoroute

AutoRoute is a routing table plus eight subagents. The session reads its own model tier from a block in `CLAUDE.md` and, instead of doing lookups and boilerplate itself, hands them to subagents whose model is pinned in their frontmatter — Haiku for finding and reading, Sonnet for implementation, tests and review, Opus for UI judgment. Each subagent that cannot finish a task returns a fixed `ESCALATE` block naming the next rung up, so nothing jumps straight from Haiku to Opus on a guess.

## Install

```bash
git clone https://github.com/Bijaykars/claude-code-autoroute
cd claude-code-autoroute
python install.py
```

Restart Claude Code. That is the whole setup. By default it only writes a marked block into `CLAUDE.md` and copies the agent and hook files; your own rules and preferences are left alone.

## One task, end to end

A nightly job on my project writes a rank column, and a test that asserts contiguous ranks started failing: instead of `1, 2, 3, 4`, a run produced ranks like `1, 2, 3, 5`. I didn't know why, and I didn't want to spend top-model tokens finding out.

The brief I gave `deep-debug` (Sonnet) was: reproduce the gap, read the writer that assigns ranks, generate at least three competing hypotheses before touching any of them, and don't propose a fix until you can show the mechanism at a specific file and line. That shape of brief is written into the agent's own instructions, not something I restate each time.

It came back with the mechanism: the writer assigned rank from a row's position in an array, but a minimum-history filter dropped a freshly listed symbol after the array was built, so the index skipped a number for every row the filter removed downstream. The fix replaced the array-index rank with a counter that only advances on rows actually written. It re-ran the failing test, then the full suite, both green.

It also appended one line to its own ledger: `| date | rank gap in nightly writer | resolved | sonnet |`. That row is what later lets a `retune` agent decide, from outcomes rather than my impression, whether `deep-debug` should keep starting on Sonnet or needs to start on Opus. No Opus tokens were spent on this bug at all.

## What I observed on one working day

I'm not going to claim a controlled benchmark from one day on one project, but the numbers are worth showing with their caveats attached. On 2026-09-14 I logged twenty-two delegated tasks — repo searches, log digests, the rank-gap-style bug fix above, a new UI tab, a code review, two research batteries, a theme pass, one web research task — and read off the token counts each subagent reported on completion:

| tier | tokens | blended $/M (80/20 in/out) | cost |
|---|---|---|---|
| Haiku 4.5 | 462k | 1.80 | $0.83 |
| Sonnet 5 | 1,725k | 3.60 | $6.21 |
| Opus 5 | 275k | 9.00 | $2.48 |
| Fable 5.1 | 211k | 18.00 | $3.80 |
| routed total | 2,673k | | $13.32 |
| same tokens, all on Fable 5.1 | 2,673k | 18.00 | $48.12 |

The routed total came to 28% of the all-top-model price for the same tokens. The caveats matter as much as the number: this excludes the orchestrating session's own tokens, the dollar figures are estimated from reported totals at an assumed 80/20 input/output split rather than real input/output/cache accounting, and it is one day on one project with one operator. Treat it as an order of magnitude, not a benchmark.

## What did not work, the first time

Two things broke before I got a clean run. First, the early versions of the agents never wrote a ledger row at all — I had told them to "log the outcome" without saying where, and an instruction without an explicit path is one an agent will happily skip. The fix was mechanical: every agent's instructions now name the exact file, `.claude/agent-memory/<agent>/MEMORY.md`, and the exact row format.

Second, I placed the retune marker above the ledger table instead of below it, which meant `retune` recounted rows from a previous tuning cycle as if they were new evidence every time it ran, biasing the fail-rate calculation toward whatever had already been reverted once. Moving the marker below the table and having `retune` read only rows after it fixed the double-count.

## What's next

I want to package this as a Claude Code plugin with install verification and a clean uninstall, instead of a script that copies files around. And I want a real three-way comparison — ordinary Claude Code, fixed model assignments, routing with retuning — measured on task success, total cost including the orchestrating session, elapsed time and retries, rather than the single-day estimate above.

Repo: https://github.com/Bijaykars/claude-code-autoroute
