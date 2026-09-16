# PostToolUse hook: count consecutive inline tool calls; nudge to delegate after N.
# Agent calls reset the streak. Any failure is a silent no-op.
import json, os, re, sys, tempfile
try:
    p = json.load(sys.stdin)
    # Claude Code stamps hook payloads fired inside a subagent with one of these
    # identifiers. A subagent's own tool calls must never advance the PARENT
    # session's inline-tool streak, so bail out before touching the counter file.
    if any(p.get(k) for k in ("agent_id", "agent_type", "subagent_id", "parent_session_id")):
        sys.exit(0)
    tool = p.get("tool_name", "")
    sid = re.sub(r"[^A-Za-z0-9-]", "", str(p.get("session_id") or "default")) or "default"
    f = os.path.join(tempfile.gettempdir(), "delegate-count-" + sid)
    if tool == "Agent":
        open(f, "w").write("0"); sys.exit(0)
    if tool not in {"Bash", "Read", "Grep", "Glob", "Edit", "Write", "PowerShell"}:
        sys.exit(0)
    try: n = int(open(f).read().strip())
    except Exception: n = 0
    n += 1
    open(f, "w").write(str(n))
    T = int(os.environ.get("DELEGATE_TRIPWIRE", "4"))
    if n >= T and (n - T) % 6 == 0:
        msg = (f"[orchestrator] {n} consecutive inline tool calls without delegating. "
               "This block belongs to an agent: locate/digest for reading, implement/scaffold for edits. "
               "Delegate the remainder now. Subagents executing a delegated task: ignore this notice.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
except Exception:
    pass
