# Plugin install (experimental)

See also: [install.md](install.md) (the non-plugin installer) · [self-tuning.md](self-tuning.md) (the ledger this plugin's hooks write).

AutoRoute 0.3 ships as a Claude Code plugin, packaged from the same `agents/`,
`hooks/` and `commands/` this repo already had. This path is newer and less
exercised than `install.py`; treat it as experimental.

## Install

```
/plugin marketplace add Bijaykars/claude-code-autoroute
/plugin install autoroute
```

or, from the CLI:

```bash
claude plugin marketplace add Bijaykars/claude-code-autoroute
claude plugin install autoroute
```

The repo carries its own `.claude-plugin/marketplace.json` (a single-plugin,
self-hosted marketplace pointing at `./`), so no separate marketplace repo is
needed.

The plugin does not install a `CLAUDE.md` routing block — plugins cannot edit
your `CLAUDE.md`. `hooks/prompt-nudge.py` detects it is running under the
plugin (`CLAUDE_PLUGIN_ROOT` is set) and appends a compact 6-line routing
summary to its own reminder each turn, so the tiers are still visible without
the full philosophy sections `install.py --full-claude-md` would add.

## What the hooks capture

Three hooks existed before 0.3 (`retune-due.py`, `prompt-nudge.py`,
`inline-counter.py`, unchanged in shape). 0.3 adds `hooks/ledger.py`, wired to
three events:

- `PreToolUse` (matcher `Agent`) — records a pending delegation: session,
  subagent type, description, model override, and the first 200 characters of
  the prompt.
- `SubagentStart` — matches the pending entry to the subagent that actually
  started (same session, same subagent type; oldest first) and starts a timer.
- `SubagentStop` — reads the subagent's own transcript, and appends one `run`
  event to the ledger: model actually used, the agent's configured
  model/effort, resolved-or-escalated outcome, the `NEXT:` line if escalated,
  a count of tool errors, wall-clock duration, and summed token usage.

This never raises and never blocks a tool call; any failure is a silent no-op,
because a ledger hook must not be able to break a session.

## Where the ledger lives

`<project>/.claude/autoroute/ledger.jsonl` — one JSON object per line, one
line per event (`run`, `wrong`, or `retune`). Working state used only to
correlate the three hook events lives alongside it: `pending.jsonl` and
`active.json`; both are scratch files, safe to delete.

Agents still additionally write their own MEMORY.md ledger rows this release
— both sources are kept side by side, and `retune-due.py` / `agents/retune.md`
report whichever source has more rows for a given agent. The MEMORY.md rows
are not being removed yet.

## The off switch

```bash
python autoroute.py off   # or the /autoroute off slash command
python autoroute.py on
```

Creates or removes `~/.claude/autoroute/off` (global, not per-project). While
it exists: `hooks/ledger.py` exits immediately and writes nothing, and
`hooks/prompt-nudge.py` replaces its usual reminder with
`[autoroute] OFF — do not delegate; work inline`.

## Commands

`python autoroute.py <command>`, or the `/autoroute <command>` slash command
when installed as a plugin:

- `status` — per-agent runs/escalated/wrong since the last retune marker, and
  a `RETUNE DUE` flag at the same thresholds `retune-due.py` uses.
- `stats` — an agent x model table (runs, success %, escalated, wrong, median
  duration, total tokens), all-time and last 30 days.
- `why <agent> [words...]` — the agent's configured tier, its per-model record
  in this project, and (if words are given) the same record filtered to tasks
  matching those words. Cells with N < 10 are marked "insufficient data" and
  never carry a recommendation. Prints an expected-cost-per-success figure
  only when every displayed cell has N >= 10.
- `wrong <agent_id|last> "<why>"` — appends a `wrong` event; this replaces
  hand-writing a WRONG row in the agent's MEMORY.md ledger table.
- `off` / `on` — the global switch above.
- `mark-retune <agent> "<note>"` — appends a `retune` event; `agents/retune.md`
  calls this instead of writing a markdown marker when the JSONL ledger
  exists.
