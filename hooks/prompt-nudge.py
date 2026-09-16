# UserPromptSubmit hook: re-assert delegation every prompt so it survives long sessions and compaction.
# Reads the same DELEGATE_TRIPWIRE env var (default 4) as inline-counter.py so the two hooks never quote
# conflicting thresholds.
#
# v0.3: honours the global off switch (~/.claude/autoroute/off) and, when running
# under the plugin (no CLAUDE.md routing block installed), appends a compact
# routing summary so the plugin works standalone.
import json
import os
from pathlib import Path

T = int(os.environ.get("DELEGATE_TRIPWIRE", "4"))

PLUGIN_SUMMARY = (
    "\n[autoroute] Routing (plugin mode, no CLAUDE.md block installed):\n"
    "Fable/Opus: decide, plan, judge, risky edits -> delegate everything else.\n"
    "Sonnet: also implements well-specified changes -> delegate searching/reading/boilerplate.\n"
    "locate/digest (haiku): find and read only, never write code.\n"
    "scaffold/implement/test-writer/reviewer (sonnet): mechanical edits, implementation, tests, review.\n"
    "deep-debug (sonnet, self-escalates to opus) / retune (re-tiers agents from the ledger)."
)


def is_off():
    try:
        return (Path.home() / ".claude" / "autoroute" / "off").exists()
    except Exception:
        return False


if is_off():
    context = "[autoroute] OFF — do not delegate; work inline"
else:
    context = (
        "[orchestrator] Reminder: you plan and judge; agents read, search, edit, test. "
        f"Before the {T}th consecutive inline Read/Grep/Bash/Edit, hand the block to an agent."
    )
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        context += PLUGIN_SUMMARY

print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
