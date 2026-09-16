# UserPromptSubmit hook: re-assert delegation every prompt so it survives long sessions and compaction.
import json
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
  "[orchestrator] Reminder: you plan and judge; agents read, search, edit, test. "
  "Before a 3rd consecutive inline Read/Grep/Bash/Edit, hand the block to an agent."}}))
