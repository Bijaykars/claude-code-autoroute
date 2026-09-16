# UserPromptSubmit hook: re-assert delegation every prompt so it survives long sessions and compaction.
# Reads the same DELEGATE_TRIPWIRE env var (default 4) as inline-counter.py so the two hooks never quote
# conflicting thresholds.
import json, os
T = int(os.environ.get("DELEGATE_TRIPWIRE", "4"))
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
  "[orchestrator] Reminder: you plan and judge; agents read, search, edit, test. "
  f"Before the {T}th consecutive inline Read/Grep/Bash/Edit, hand the block to an agent."}}))
