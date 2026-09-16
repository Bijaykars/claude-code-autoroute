# PreToolUse(Agent) / SubagentStart / SubagentStop hook: hook-captured ledger.
#
# Field names below were verified against the installed Claude Code CLI binary
# (v2.1.243), not just the docs, because the docs available at implementation
# time did not list SubagentStart and did not show the SubagentStop payload
# shape. Two things differ from a naive reading of "the transcript at
# transcript_path":
#   - SubagentStop's own `transcript_path` field is the PARENT session's
#     transcript. The subagent's own transcript is `agent_transcript_path`.
#     This script reads `agent_transcript_path`, falling back to
#     `transcript_path` only if the former is absent (defensive, e.g. an
#     older/newer CLI).
#   - SubagentStart carries `agent_type` (not `subagent_type`); it is matched
#     against the `subagent_type` recorded from the PreToolUse Agent call.
#
# Never raises: any failure anywhere below is swallowed and the hook exits 0,
# because a ledger hook must never break the session.
import json
import os
import re
import sys
import time
from pathlib import Path

ESCALATE_RE = re.compile(r"(?m)^ESCALATE:")
NEXT_RE = re.compile(r"(?m)^NEXT:\s*(.+?)\s*$")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def model_tier(model_id):
    """claude-sonnet-5 -> sonnet, claude-opus-5 -> opus, etc. Unknown/empty ->
    'unknown'. Used so pricing and per-model tables key on the same tier
    names as BLENDED_PER_M, not the raw model id."""
    if not model_id:
        return "unknown"
    m = model_id.lower()
    for tier in ("haiku", "sonnet", "opus"):
        if tier in m:
            return tier
    if "fable" in m or "mythos" in m:
        return "fable"
    return "unknown"


def is_off():
    try:
        return (Path.home() / ".claude" / "autoroute" / "off").exists()
    except Exception:
        return False


def autoroute_dir(cwd):
    d = Path(cwd) / ".claude" / "autoroute"
    d.mkdir(parents=True, exist_ok=True)
    return d


def active_dir(cwd):
    """One file per running agent (<agent_id>.json) instead of a single
    active.json, so parallel SubagentStart/SubagentStop hooks never
    read-modify-write the same file."""
    d = autoroute_dir(cwd) / "active"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_jsonl(path):
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def write_jsonl(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")


def write_jsonl_atomic(path, items):
    """Write-to-temp-then-os.replace so a pop that races another process's
    read never leaves pending.jsonl half-written."""
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{time.time_ns()}")
    write_jsonl(tmp, items)
    os.replace(tmp, path)


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def load_agent_frontmatter(agent_type, cwd):
    """model:/effort: from the project's agent file first, else the global one."""
    if not agent_type:
        return None, None
    candidates = [
        Path(cwd) / ".claude" / "agents" / f"{agent_type}.md",
        Path.home() / ".claude" / "agents" / f"{agent_type}.md",
    ]
    for c in candidates:
        try:
            text = c.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = FRONTMATTER_RE.match(text)
        if not m:
            continue
        fm = m.group(1)
        mm = re.search(r"(?m)^model:\s*(\S+)", fm)
        em = re.search(r"(?m)^effort:\s*(\S+)", fm)
        return (mm.group(1).strip() if mm else None, em.group(1).strip() if em else None)
    return None, None


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c.get("text") or "" for c in content if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(parts)
    return ""


def parse_transcript(path):
    """(model, tool_errors, tokens|None, last_assistant_text|None). Tolerates
    JSONL lines that are not chat messages; never raises."""
    model = None
    tool_errors = 0
    tin = tout = 0
    have_usage = False
    last_text = None
    if not path:
        return model, tool_errors, None, last_text
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return model, tool_errors, None, last_text
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        t = obj.get("type")
        if t == "assistant":
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            if msg.get("model"):
                model = msg.get("model")
            usage = msg.get("usage")
            if isinstance(usage, dict) and ("input_tokens" in usage or "output_tokens" in usage):
                have_usage = True
                tin += usage.get("input_tokens") or 0
                tout += usage.get("output_tokens") or 0
            text = extract_text(msg.get("content"))
            if text.strip():
                last_text = text
        elif t == "user":
            msg = obj.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                        tool_errors += 1
    tokens = {"input": tin, "output": tout} if have_usage else None
    return model, tool_errors, tokens, last_text


def handle_pretooluse(payload, cwd):
    if payload.get("tool_name") != "Agent":
        return
    tool_input = payload.get("tool_input") or {}
    entry = {
        "ts": time.time(),
        "session_id": payload.get("session_id"),
        "subagent_type": tool_input.get("subagent_type"),
        "description": tool_input.get("description"),
        "model_override": tool_input.get("model"),
        "prompt_head": (tool_input.get("prompt") or "")[:200],
    }
    append_jsonl(autoroute_dir(cwd) / "pending.jsonl", entry)


def pop_pending(pending_path, session_id, agent_type):
    """Choose the oldest pending entry for the same session and subagent
    type; fall back to the oldest entry for the same session. Rewrite the
    file without the chosen line via write-to-temp-then-replace so a
    concurrent reader never sees a partially written file."""
    pending = read_jsonl(pending_path)

    match_idx = None
    for i, p in enumerate(pending):
        if p.get("session_id") == session_id and p.get("subagent_type") == agent_type:
            match_idx = i
            break
    if match_idx is None:
        for i, p in enumerate(pending):
            if p.get("session_id") == session_id:
                match_idx = i
                break
    if match_idx is None:
        return {}

    matched = pending.pop(match_idx)
    write_jsonl_atomic(pending_path, pending)
    return matched


def handle_subagentstart(payload, cwd):
    agent_id = payload.get("agent_id")
    if not agent_id:
        return
    session_id = payload.get("session_id")
    agent_type = payload.get("agent_type")
    d = autoroute_dir(cwd)
    matched = pop_pending(d / "pending.jsonl", session_id, agent_type)

    entry = {
        "ts": time.time(),
        "session_id": session_id,
        "subagent_type": agent_type,
        "description": matched.get("description"),
        "model_override": matched.get("model_override"),
        "prompt_head": matched.get("prompt_head"),
    }
    write_json(active_dir(cwd) / f"{agent_id}.json", entry)


def handle_subagentstop(payload, cwd):
    d = autoroute_dir(cwd)
    agent_id = payload.get("agent_id")
    session_id = payload.get("session_id")
    agent_type = payload.get("agent_type")

    # No agent_id, or no matching start file (orphan stop): started stays
    # None and the event below records duration=None, task=None rather than
    # raising.
    started = None
    if agent_id:
        active_path = active_dir(cwd) / f"{agent_id}.json"
        started = read_json(active_path, None)
        try:
            active_path.unlink(missing_ok=True)
        except Exception:
            pass

    transcript_path = payload.get("agent_transcript_path") or payload.get("transcript_path")
    model, tool_errors, tokens, transcript_last_text = parse_transcript(transcript_path)

    final_text = payload.get("last_assistant_message") or transcript_last_text or ""
    outcome = "escalated" if ESCALATE_RE.search(final_text) else "resolved"
    nm = NEXT_RE.search(final_text)
    next_line = nm.group(1) if nm else None

    model_override = started.get("model_override") if started else None
    configured_model, configured_effort = load_agent_frontmatter(agent_type, cwd)

    ts = time.time()
    start_ts = started.get("ts") if started else None
    duration_s = (ts - start_ts) if start_ts is not None else None
    resolved_model = model or model_override

    event = {
        "type": "run",
        "ts": ts,
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "project": cwd,
        "task": started.get("description") if started else None,
        "model": resolved_model,
        "model_tier": model_tier(resolved_model),
        "configured_model": configured_model,
        "configured_effort": configured_effort,
        "outcome": outcome,
        # `outcome == "resolved"` means the subagent finished without
        # escalating -- it is NOT a correctness signal. `verified` stays
        # null until a caller runs `autoroute.py wrong` (-> false) or
        # `autoroute.py ok` (-> true) against this run's agent_id.
        "verified": None,
        "next": next_line,
        "tool_errors": tool_errors,
        "duration_s": duration_s,
        "tokens": tokens,
        "wrong": False,
    }
    append_jsonl(d / "ledger.jsonl", event)


def main():
    if is_off():
        return
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    event = payload.get("hook_event_name")
    if event == "PreToolUse":
        handle_pretooluse(payload, cwd)
    elif event == "SubagentStart":
        handle_subagentstart(payload, cwd)
    elif event == "SubagentStop":
        handle_subagentstop(payload, cwd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
