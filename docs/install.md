# Install

See also: [escalation.md](escalation.md) (the ESCALATE contract) · [self-tuning.md](self-tuning.md) (the retune loop).

## What `install.py` does

```bash
python install.py            # install
python install.py --dry-run  # show what would happen, change nothing
python install.py --uninstall
python install.py --full-claude-md  # also install the coding-philosophy sections
```

Step by step, on a plain install:

1. **Agents.** Creates `~/.claude/agents/` if it does not exist, then copies each
   `agents/*.md` into it. Anything it would overwrite is backed up first to
   `<file>.bak-<timestamp>` in the same directory.
2. **Hooks.** Same pattern for `hooks/*.py` into `~/.claude/hooks/`, plus
   `autoroute.py` itself (the CLI is copied alongside the hooks so a hook can
   `import` it without extra path setup). Six hook events get wired, one line
   each:
   - `SessionStart` (`retune-due.py`) — flags an agent whose ledger has enough
     rows since its last retune marker.
   - `UserPromptSubmit` (`prompt-nudge.py`) — re-asserts the routing rule.
   - `PostToolUse` (`inline-counter.py`) — nudges after N consecutive inline
     tool calls without delegating.
   - `PreToolUse`, matcher `Agent` (`ledger.py`) — records a pending
     delegation before the subagent starts.
   - `SubagentStart` (`ledger.py`) — matches the pending entry and starts a
     timer, in `.claude/autoroute/active/<agent_id>.json`.
   - `SubagentStop` (`ledger.py`) — appends the completed run to
     `.claude/autoroute/ledger.jsonl`.
3. **`CLAUDE.md`.**
   - No `~/.claude/CLAUDE.md` yet: by default it writes only the marked routing
     block — section 0, "Cost routing" — wrapped in
     `<!-- autoroute:start -->` / `<!-- autoroute:end -->` markers, as a new file.
     Your own coding preferences are never overwritten because there is nothing
     to overwrite.
   - Pass `--full-claude-md` to install the complete `CLAUDE.md` instead (routing
     plus the Karpathy/Ponytail sections) for people who want the whole
     philosophy, not just the routing rule.
   - An existing `~/.claude/CLAUDE.md` is never replaced wholesale: install.py
     extracts section 0 from this repo's `CLAUDE.md` and either replaces the
     `<!-- autoroute:start -->...<!-- autoroute:end -->` block if one is already
     there, or appends a fresh marked block at the end. Everything else in your
     file is untouched. The file is backed up before the edit.
4. **`settings.json`.** Merges the six hook entries from
   `settings.example.json` into `~/.claude/settings.json` (creating it if
   needed), matched by hook filename so re-running the installer never adds a
   duplicate entry for a hook that is already wired. Each entry's `command` is
   an absolute path (forward slashes, quoted) built from this machine's actual
   home directory — no `$HOME`/`$env:USERPROFILE` shell variable, so the same
   command runs under any shell. The file is backed up before any write.

`--dry-run` prints the same action log without touching disk — run it first to
see exactly what would change.

`--uninstall` reverses each step: agent and hook files are restored from their
newest `.bak-*` file if one exists, or deleted if the installer created them
fresh. The `settings.json` hook entries this tool added are removed. For
`CLAUDE.md`: the marked block is stripped if one is present; if there is no
marker (a fresh full-copy install with nothing to merge into), the newest
backup is restored, or the file is removed if the installer created it from
nothing.

## Manual install

If you would rather not run the script:

```bash
mkdir -p ~/.claude/agents && cp agents/*.md ~/.claude/agents/
mkdir -p ~/.claude/hooks && cp hooks/*.py ~/.claude/hooks/
# then merge settings.example.json into ~/.claude/settings.json by hand,
# and merge CLAUDE.md's section 0 into your own CLAUDE.md
# (or copy the whole file if you don't have one yet)
```

## Keep your own CLAUDE.md

AutoRoute never touches anything in your `CLAUDE.md` outside the marked block.
Your existing rules, project conventions and coding preferences survive
reinstalls and uninstalls untouched.

## Ledgers

The primary ledger is `.claude/autoroute/ledger.jsonl` inside the current
project, one JSON object per line (`run`, `wrong`, `retune`, `ok`), captured
automatically by `hooks/ledger.py` on every delegation — no agent cooperation
required. `outcome: "resolved"` means the subagent finished without
escalating; it is not a correctness signal. Run `python autoroute.py wrong
<agent_id|last> "<why>"` or `python autoroute.py ok <agent_id|last>` to record
that a result was actually checked. See
[self-tuning.md](self-tuning.md) for the full field list.

Each agent additionally writes its own row to
`.claude/agent-memory/<agent>/MEMORY.md` — the pre-0.3 mechanism, kept as a
fallback for a project or agent where the JSONL ledger has no rows yet. These
files accumulate per project. Git-ignore `.claude/agent-memory/` and
`.claude/autoroute/` in a project if you do not want the ledgers committed
alongside your code.

## The off switch

```bash
python autoroute.py off   # or /autoroute off under the plugin
python autoroute.py on
```

Creates or removes `~/.claude/autoroute/off` (global, not per-project). While
it exists, `hooks/ledger.py` writes nothing and `hooks/prompt-nudge.py`
replaces its reminder with `[autoroute] OFF — do not delegate; work inline`.

## Raising the delegation tripwire

`hooks/inline-counter.py` nudges the session to delegate after four
consecutive inline tool calls by default (`DELEGATE_TRIPWIRE`, default `4`).
If that fires too eagerly for your workflow, raise it in your project or user
`settings.json`, under the top-level `env` block:

```json
{
  "env": { "DELEGATE_TRIPWIRE": "8" }
}
```

`hooks/prompt-nudge.py` reads the same variable so both hooks stay in sync.
