#!/usr/bin/env python
"""AutoRoute CLI -- reads the hook-captured ledger at
`<cwd>/.claude/autoroute/ledger.jsonl` (written by hooks/ledger.py) and
answers routing questions for THIS project.

    python autoroute.py status
    python autoroute.py stats
    python autoroute.py why <agent_type> [task words...]
    python autoroute.py wrong <agent_id|last> "<why>"
    python autoroute.py off | on
    python autoroute.py mark-retune <agent_type> "<note>"

Stdlib only, Python 3.9+. Runs from the project directory the ledger belongs
to (it reads `os.getcwd()`, same convention as the hooks).
"""
import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

BLENDED_PER_M = {"haiku": 1.80, "sonnet": 3.60, "opus": 9.00, "fable": 18.00}
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
DAY = 86400


def off_path():
    return Path.home() / ".claude" / "autoroute" / "off"


def is_off():
    try:
        return off_path().exists()
    except Exception:
        return False


def ledger_path(cwd):
    return Path(cwd) / ".claude" / "autoroute" / "ledger.jsonl"


def load_rows(cwd):
    path = ledger_path(cwd)
    rows = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def append_event(cwd, obj):
    path = ledger_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def wrong_refs(rows):
    return {r.get("ref") for r in rows if r.get("type") == "wrong" and r.get("ref")}


def runs(rows):
    return [r for r in rows if r.get("type") == "run"]


def is_success(r, wrongset):
    return r.get("outcome") == "resolved" and r.get("agent_id") not in wrongset


def load_agent_frontmatter(agent_type, cwd):
    if not agent_type:
        return None, None
    for c in (Path(cwd) / ".claude" / "agents" / f"{agent_type}.md", Path.home() / ".claude" / "agents" / f"{agent_type}.md"):
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


# ---- since-last-retune counting (mirrors hooks/retune-due.py's count_from_ledger) ----
def count_since_retune(rows):
    indexed = list(enumerate(rows))
    last_retune_idx = {}
    for i, obj in indexed:
        if obj.get("type") == "retune" and obj.get("agent"):
            last_retune_idx[obj["agent"]] = i
    counts = {}
    run_agent_of = {}
    for i, obj in indexed:
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
    for i, obj in indexed:
        if obj.get("type") == "wrong":
            agent = run_agent_of.get(obj.get("ref"))
            if agent and agent in counts:
                counts[agent]["w"] += 1
    return counts


def cmd_status(args, cwd):
    rows = load_rows(cwd)
    counts = count_since_retune(rows)
    print(f"autoroute: {'OFF' if is_off() else 'ON'}")
    if not counts:
        print("(no runs recorded in this project's ledger yet)")
        return
    print(f"{'agent':<16}{'N':>5}{'escalated':>11}{'wrong':>7}{'fail_rate':>11}  flag")
    for agent in sorted(counts):
        c = counts[agent]
        n, e, w = c["n"], c["e"], c["w"]
        rate = (e + w) / n if n else 0.0
        flag = "RETUNE DUE" if (n >= 10 or w >= 3) else ""
        print(f"{agent:<16}{n:>5}{e:>11}{w:>7}{rate:>11.2f}  {flag}")


def token_total(r):
    t = r.get("tokens")
    if not isinstance(t, dict):
        return None
    i, o = t.get("input"), t.get("output")
    if i is None and o is None:
        return None
    return (i or 0) + (o or 0)


def cmd_stats(args, cwd):
    rows = load_rows(cwd)
    all_runs = runs(rows)
    wset = wrong_refs(rows)
    now = time.time()

    def table(subset, title):
        print(f"\n{title}")
        if not subset:
            print("  (no runs)")
            return
        groups = {}
        for r in subset:
            key = (r.get("agent_type") or "unknown", r.get("model") or "unknown")
            groups.setdefault(key, []).append(r)
        print(f"  {'agent':<16}{'model':<10}{'runs':>6}{'success%':>10}{'escalated':>11}{'wrong':>7}{'median_s':>10}{'tokens':>12}")
        for (agent, model) in sorted(groups):
            g = groups[(agent, model)]
            n = len(g)
            succ = sum(1 for r in g if is_success(r, wset))
            esc = sum(1 for r in g if r.get("outcome") == "escalated")
            wr = sum(1 for r in g if r.get("agent_id") in wset)
            durs = [r["duration_s"] for r in g if isinstance(r.get("duration_s"), (int, float))]
            med = f"{statistics.median(durs):.1f}" if durs else "n/a"
            toks = [token_total(r) for r in g]
            toks = [t for t in toks if t is not None]
            tot_tok = sum(toks) if toks else 0
            print(f"  {agent:<16}{model:<10}{n:>6}{(succ / n * 100):>9.0f}%{esc:>11}{wr:>7}{med:>10}{tot_tok:>12}")

    table(all_runs, "All time")
    recent = [r for r in all_runs if isinstance(r.get("ts"), (int, float)) and r["ts"] >= now - 30 * DAY]
    table(recent, "Last 30 days")


def cmd_why(args, cwd):
    agent = args.agent_type
    words = args.words or []
    rows = load_rows(cwd)
    all_runs = [r for r in runs(rows) if r.get("agent_type") == agent]
    wset = wrong_refs(rows)

    model, effort = load_agent_frontmatter(agent, cwd)
    print(f"{agent}: configured tier = model={model or 'unknown'} effort={effort or 'unknown'}")

    def cells_for(subset):
        groups = {}
        for r in subset:
            groups.setdefault(r.get("model") or "unknown", []).append(r)
        return groups

    def print_cells(groups, label):
        print(f"\n{label} (this project):")
        if not groups:
            print("  (no runs)")
            return {}
        result = {}
        for model_name in sorted(groups):
            g = groups[model_name]
            n = len(g)
            if n < 10:
                print(f"  {model_name}: insufficient data (N={n}) -- default tier applies")
                result[model_name] = None
                continue
            succ = sum(1 for r in g if is_success(r, wset)) / n * 100
            print(f"  {model_name}: N={n} success={succ:.0f}%")
            toks = [token_total(r) for r in g]
            toks = [t for t in toks if t is not None]
            mean_tok = (sum(toks) / len(toks)) if toks else None
            success_rate = succ / 100.0
            result[model_name] = {"n": n, "success_rate": success_rate, "mean_tokens": mean_tok}
        return result

    base_cells = print_cells(cells_for(all_runs), "Per-model record")

    matched_cells = None
    if words:
        wl = [w.lower() for w in words]
        matched = [r for r in all_runs if r.get("task") and any(w in r["task"].lower() for w in wl)]
        matched_cells = print_cells(cells_for(matched), f"Matching task words {words}")

    print(
        "\nObjective: lowest expected cost to a successful completion, including "
        "retries -- computed only when every cell has N >= 10."
    )

    considered = list(base_cells.values()) + (list(matched_cells.values()) if matched_cells is not None else [])
    if considered and all(c is not None for c in considered):
        print("Expected cost per model (blended $/M x mean tokens / success rate):")
        for label, groups in (("base", base_cells), ("task-filtered", matched_cells or {})):
            for model_name, c in groups.items():
                if c is None:
                    continue
                rate = BLENDED_PER_M.get(model_name)
                if rate is None or c["mean_tokens"] is None or c["success_rate"] <= 0:
                    print(f"  [{label}] {model_name}: no token data")
                    continue
                cost = rate * (c["mean_tokens"] / 1_000_000) / c["success_rate"]
                print(f"  [{label}] {model_name}: ${cost:.4f} expected per successful run")


def cmd_wrong(args, cwd):
    rows = load_rows(cwd)
    ref = args.agent_id
    if ref == "last":
        last_run = None
        for r in rows:
            if r.get("type") == "run":
                last_run = r
        if not last_run:
            print("no runs recorded in this project's ledger yet")
            return 1
        ref = last_run.get("agent_id")
    append_event(cwd, {"type": "wrong", "ref": ref, "why": args.why, "ts": time.time()})
    print(f"marked {ref} wrong: {args.why}")
    print("(this replaces hand-writing a WRONG row in the agent's MEMORY.md ledger table)")


def cmd_off(args, cwd):
    p = off_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    print("autoroute: OFF")


def cmd_on(args, cwd):
    p = off_path()
    if p.exists():
        p.unlink()
    print("autoroute: ON")


def cmd_mark_retune(args, cwd):
    append_event(cwd, {"type": "retune", "agent": args.agent_type, "note": args.note, "ts": time.time()})
    print(f"marked retune for {args.agent_type}: {args.note}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="per-agent runs/escalated/wrong since last retune, and RETUNE DUE flags")
    sub.add_parser("stats", help="agent x model table: runs, success%, escalated, wrong, median duration, tokens")

    p_why = sub.add_parser("why", help="why an agent is tiered the way it is, evidence permitting")
    p_why.add_argument("agent_type")
    p_why.add_argument("words", nargs="*")

    p_wrong = sub.add_parser("wrong", help="mark a delegated run wrong")
    p_wrong.add_argument("agent_id", help="an agent_id from the ledger, or 'last'")
    p_wrong.add_argument("why")

    sub.add_parser("off", help="turn autoroute off (global switch)")
    sub.add_parser("on", help="turn autoroute on (global switch)")

    p_mr = sub.add_parser("mark-retune", help="append a retune marker event")
    p_mr.add_argument("agent_type")
    p_mr.add_argument("note")

    args = ap.parse_args()
    cwd = os.getcwd()
    handlers = {
        "status": cmd_status,
        "stats": cmd_stats,
        "why": cmd_why,
        "wrong": cmd_wrong,
        "off": cmd_off,
        "on": cmd_on,
        "mark-retune": cmd_mark_retune,
    }
    return handlers[args.command](args, cwd) or 0


if __name__ == "__main__":
    sys.exit(main())
