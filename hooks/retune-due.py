# SessionStart hook: flag agents whose ledger has enough new rows since their last
# "## Retune" marker for retune to judge. Silent when nothing is due or on any error.
# Contract: retune.md always appends its marker at the END of the file, below a fresh
# table, so rows above the newest marker were already judged and must never be
# recounted here — hence "since=lines after the last marker" below.
#
# v0.3: also reads the hook-captured `.claude/autoroute/ledger.jsonl` (written by
# hooks/ledger.py). Both sources are counted per agent; whichever has MORE rows
# for that agent is reported (the JSONL ledger is the more complete source once
# it has been running a while, but a fresh install has zero rows in it and must
# fall back to the agent-written MEMORY.md rows).
import json, os, re, sys, glob

ROW = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|[^|]*\|\s*([^|]*?)\s*\|")
MULT = re.compile(r"[×x]\s*(\d+)")


def count_from_memory(cwd):
    out = {}
    for f in glob.glob(os.path.join(cwd, ".claude", "agent-memory", "*", "MEMORY.md")):
        agent = os.path.basename(os.path.dirname(f))
        lines = open(f, encoding="utf-8", errors="replace").read().splitlines()
        marks = [i for i, l in enumerate(lines) if l.startswith("## Retune")]
        since = lines[marks[-1]:] if marks else lines
        n = e = w = 0
        for l in since:
            m = ROW.match(l)
            if not m:
                continue
            cell = m.group(1).lower()
            k = int(MULT.search(cell).group(1)) if MULT.search(cell) else 1
            if cell.startswith("resolved"):
                n += k
            elif cell.startswith("escalated"):
                n += k; e += k
            elif cell.startswith("wrong"):
                w += k
        out[agent] = {"n": n, "e": e, "w": w}
    return out


def count_from_ledger(cwd):
    path = os.path.join(cwd, ".claude", "autoroute", "ledger.jsonl")
    if not os.path.isfile(path):
        return {}
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append((i, obj))

    last_retune_idx = {}
    for i, obj in rows:
        if obj.get("type") == "retune" and obj.get("agent"):
            last_retune_idx[obj["agent"]] = i

    counts = {}
    run_agent_of = {}
    for i, obj in rows:
        if obj.get("type") != "run":
            continue
        agent = obj.get("agent_type")
        if not agent or i <= last_retune_idx.get(agent, -1):
            continue
        c = counts.setdefault(agent, {"n": 0, "e": 0, "w": 0})
        c["n"] += 1
        if obj.get("outcome") == "escalated":
            c["e"] += 1
        if obj.get("agent_id"):
            run_agent_of[obj["agent_id"]] = agent

    for i, obj in rows:
        if obj.get("type") == "wrong":
            agent = run_agent_of.get(obj.get("ref"))
            if agent and agent in counts:
                counts[agent]["w"] += 1
    return counts


try:
    p = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    cwd = p.get("cwd") or os.getcwd()
    mem = count_from_memory(cwd)
    ledger = count_from_ledger(cwd)
    due = []
    for agent in sorted(set(mem) | set(ledger)):
        m = mem.get(agent, {"n": 0, "e": 0, "w": 0})
        j = ledger.get(agent, {"n": 0, "e": 0, "w": 0})
        chosen = j if j["n"] > m["n"] else m
        n, e, w = chosen["n"], chosen["e"], chosen["w"]
        if n >= 10 or w >= 3:
            rate = f"{(e + w) / n:.2f}" if n else "n/a"
            due.append(f"{agent}: N={n} F={e + w} fail_rate={rate}")
    if due:
        msg = ("[retune] RETUNE DUE - " + "; ".join(due) +
               ". Launch the `retune` agent in the background before other work.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
except Exception:
    pass
