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
2. **Hooks.** Same pattern for `hooks/*.py` into `~/.claude/hooks/`.
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
4. **`settings.json`.** Merges the three hook entries from
   `settings.example.json` into `~/.claude/settings.json` (creating it if
   needed), matched by hook filename so re-running the installer never adds a
   duplicate entry for a hook that is already wired. The file is backed up
   before any write.

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

As agents run, each writes ledger rows to
`.claude/agent-memory/<agent>/MEMORY.md` inside the current project — one row
per completed task, plus a `WRONG` row when a caller finds a delegated answer
was incorrect. These files accumulate per project. Git-ignore
`.claude/agent-memory/` in a project if you do not want the ledgers committed
alongside your code.

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
