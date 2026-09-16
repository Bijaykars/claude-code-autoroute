---
description: Show AutoRoute routing status, stats, per-agent evidence, or manage the ledger (status/stats/why/wrong/off/on/mark-retune).
argument-hint: [status|stats|why <agent> [words...]|wrong <id|last> "<why>"|off|on|mark-retune <agent> "<note>"]
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/autoroute.py:*)
---

## AutoRoute

!`python "${CLAUDE_PLUGIN_ROOT}/autoroute.py" $ARGUMENTS`

Print the output above verbatim. Do not summarize or reformat it.
