#!/usr/bin/env python
"""AutoRoute CLI -- reads the hook-captured ledger at
`<cwd>/.claude/autoroute/ledger.jsonl` (written by hooks/ledger.py) and
answers routing questions for THIS project.

    python autoroute.py status
    python autoroute.py stats
    python autoroute.py why <agent_type> [task words...]
    python autoroute.py wrong <agent_id|last> "<why>"
    python autoroute.py ok <agent_id|last>
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


def model_tier(model_id):
    """claude-sonnet-5 -> sonnet, claude-opus-5 -> opus, etc. Unknown/empty ->
    'unknown'. Mirrors hooks/ledger.py's model_tier -- keep the two in sync."""
    if not model_id:
        return "unknown"
    m = model_id.lower()
    for tier in ("haiku", "sonnet", "opus"):
        if tier in m:
            return tier
    if "fable" in m or "mythos" in m:
        return "fable"
    return "unknown"


def row_tier(r):
    """Prefer the tier a newer ledger row already recorded; derive it from
    the raw model id for older rows that predate the model_tier field."""
    return r.get("model_tier") or model_tier(r.get("model"))


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


def ok_refs(rows):
    return {r.get("ref") for r in rows if r.get("type") == "ok" and r.get("ref")}


def runs(rows):
    return [r for r in rows if r.get("type") == "run"]


def is_non_escalated(r, wrongset):
    """True iff the subagent did not escalate and was not later marked wrong.
    This is a proxy for "did not fail loudly", NOT a correctness signal --
    printed as `non-escalated%`, never as `success%`. See `verified_counts`
    for the actual correctness signal (explicit `ok`/`wrong` calls)."""
    return r.get("outcome") == "resolved" and r.get("agent_id") not in wrongset


def effective_verified(r, wrongset, okset):
    """true/false/None (unknown). `outcome == "resolved"` only means the
    subagent did not escalate -- it is not a correctness signal on its own;
    this reflects an explicit `autoroute.py wrong`/`ok` call against the
    run's agent_id, falling back to the row's own (usually still-null)
    `verified` field."""
    aid = r.get("agent_id")
    if aid in wrongset:
        return False
    if aid in okset:
        return True
    return r.get("verified")


def verified_counts(subset, wrongset, okset):
    t = f = u = 0
    for r in subset:
        v = effective_verified(r, wrongset, okset)
        if v is True:
            t += 1
        elif v is False:
            f += 1
        else:
            u += 1
    return t, f, u


def verified_line(subset, wrongset, okset):
    """One printable line: verified success% computed ONLY over rows with an
    explicit verified true/false (an `ok`/`wrong` call against that run's
    agent_id) -- 'resolved' alone is not evidence of correctness."""
    vt, vf, vu = verified_counts(subset, wrongset, okset)
    n_verified = vt + vf
    if n_verified == 0:
        return "  verified: none yet -- use `autoroute ok|wrong`"
    rate = vt / n_verified * 100
    return (
        f"  verified: true={vt} false={vf} unknown={vu} "
        f"verified success%={rate:.0f}% (n_verified={n_verified}) "
        "('resolved' means the subagent did not escalate, not that it was correct)"
    )


def verified_cell(subset, wrongset, okset):
    """(n_verified, success_rate|None, mean_tokens|None) computed ONLY from
    rows with an explicit verified true/false -- the basis for any expected-
    cost figure, never the non-escalated proxy."""
    verified_rows = [r for r in subset if effective_verified(r, wrongset, okset) is not None]
    n_verified = len(verified_rows)
    if n_verified == 0:
        return 0, None, None
    t = sum(1 for r in verified_rows if effective_verified(r, wrongset, okset) is True)
    success_rate = t / n_verified
    toks = [token_total(r) for r in verified_rows]
    toks = [x for x in toks if x is not None]
    mean_tokens = (sum(toks) / len(toks)) if toks else None
    return n_verified, success_rate, mean_tokens


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
    okset = ok_refs(rows)
    now = time.time()

    def table(subset, title):
        print(f"\n{title}")
        if not subset:
            print("  (no runs)")
            return
        groups = {}
        raw_ids = {}
        for r in subset:
            tier = row_tier(r)
            key = (r.get("agent_type") or "unknown", tier)
            groups.setdefault(key, []).append(r)
            if r.get("model"):
                raw_ids.setdefault(tier, set()).add(r["model"])
        print(f"  {'agent':<16}{'tier':<10}{'runs':>6}{'non-escalated%':>16}{'escalated':>11}{'wrong':>7}{'median_s':>10}{'tokens':>12}")
        for (agent, tier) in sorted(groups):
            g = groups[(agent, tier)]
            n = len(g)
            non_esc = sum(1 for r in g if is_non_escalated(r, wset))
            esc = sum(1 for r in g if r.get("outcome") == "escalated")
            wr = sum(1 for r in g if r.get("agent_id") in wset)
            durs = [r["duration_s"] for r in g if isinstance(r.get("duration_s"), (int, float))]
            med = f"{statistics.median(durs):.1f}" if durs else "n/a"
            toks = [token_total(r) for r in g]
            toks = [t for t in toks if t is not None]
            tot_tok = sum(toks) if toks else 0
            print(f"  {agent:<16}{tier:<10}{n:>6}{(non_esc / n * 100):>15.0f}%{esc:>11}{wr:>7}{med:>10}{tot_tok:>12}")
        if raw_ids:
            ids_line = "; ".join(f"{tier}={','.join(sorted(ids))}" for tier, ids in sorted(raw_ids.items()))
            print(f"  raw model ids: {ids_line}")
        print(verified_line(subset, wset, okset))

    table(all_runs, "All time")
    recent = [r for r in all_runs if isinstance(r.get("ts"), (int, float)) and r["ts"] >= now - 30 * DAY]
    table(recent, "Last 30 days")


def cmd_why(args, cwd):
    agent = args.agent_type
    words = args.words or []
    rows = load_rows(cwd)
    all_runs = [r for r in runs(rows) if r.get("agent_type") == agent]
    wset = wrong_refs(rows)
    okset = ok_refs(rows)

    model, effort = load_agent_frontmatter(agent, cwd)
    print(f"{agent}: configured tier = model={model or 'unknown'} effort={effort or 'unknown'}")

    def cells_for(subset):
        groups = {}
        for r in subset:
            groups.setdefault(row_tier(r), []).append(r)
        return groups

    def print_cells(groups, label):
        print(f"\n{label} (this project):")
        if not groups:
            print("  (no runs)")
            return {}, {}
        result = {}
        vcells = {}
        raw_ids = {}
        for tier in sorted(groups):
            g = groups[tier]
            n = len(g)
            for r in g:
                if r.get("model"):
                    raw_ids.setdefault(tier, set()).add(r["model"])
            vcells[tier] = verified_cell(g, wset, okset)
            if n < 10:
                print(f"  {tier}: insufficient data (N={n}) -- default tier applies")
                result[tier] = None
                continue
            non_esc = sum(1 for r in g if is_non_escalated(r, wset)) / n * 100
            print(f"  {tier}: N={n} non-escalated={non_esc:.0f}%")
            result[tier] = {"n": n}
        if raw_ids:
            ids_line = "; ".join(f"{tier}={','.join(sorted(ids))}" for tier, ids in sorted(raw_ids.items()))
            print(f"  raw model ids: {ids_line}")
        print(verified_line([r for g in groups.values() for r in g], wset, okset))
        return result, vcells

    base_cells, base_verified = print_cells(cells_for(all_runs), "Per-model record")

    matched_verified = None
    if words:
        wl = [w.lower() for w in words]
        matched = [r for r in all_runs if r.get("task") and any(w in r["task"].lower() for w in wl)]
        _, matched_verified = print_cells(cells_for(matched), f"Matching task words {words}")

    print(
        "\nObjective: lowest expected cost to a verified successful completion, including "
        "retries -- computed only when every tier being compared has >= 10 verified "
        "(`autoroute ok`/`wrong`) runs. Never derived from the non-escalated proxy."
    )

    considered = [("base", tier, cell) for tier, cell in base_verified.items()]
    if matched_verified is not None:
        considered += [("task-filtered", tier, cell) for tier, cell in matched_verified.items()]

    if considered and all(nv >= 10 for (_, _, (nv, _, _)) in considered):
        print("Expected cost per tier (blended $/M x mean tokens / verified success rate), verified rows only:")
        for label, tier, (nv, success_rate, mean_tokens) in considered:
            rate = BLENDED_PER_M.get(tier)
            if rate is None or mean_tokens is None or not success_rate:
                print(f"  [{label}] {tier}: no token data")
                continue
            cost = rate * (mean_tokens / 1_000_000) / success_rate
            print(f"  [{label}] {tier}: ${cost:.4f} expected cost to verified success")
    elif considered:
        have = {}
        for _, tier, (nv, _, _) in considered:
            have[tier] = min(nv, have.get(tier, nv))
        have_line = ", ".join(f"{tier}={n}" for tier, n in sorted(have.items()))
        print(
            f"\nExpected cost to verified success: not available "
            f"(need >=10 verified runs per tier; have {have_line})"
        )


def resolve_ref(rows, agent_id_arg):
    """agent_id_arg is either a literal agent_id or the literal string
    'last', meaning the most recent run event's agent_id. Returns None (with
    nothing printed) if 'last' has no run to resolve against."""
    if agent_id_arg != "last":
        return agent_id_arg
    last_run = None
    for r in rows:
        if r.get("type") == "run":
            last_run = r
    return last_run.get("agent_id") if last_run else None


def cmd_wrong(args, cwd):
    rows = load_rows(cwd)
    ref = resolve_ref(rows, args.agent_id)
    if not ref:
        print("no runs recorded in this project's ledger yet")
        return 1
    append_event(cwd, {"type": "wrong", "ref": ref, "why": args.why, "ts": time.time()})
    print(f"marked {ref} wrong: {args.why}")
    print("(this replaces hand-writing a WRONG row in the agent's MEMORY.md ledger table)")


def cmd_ok(args, cwd):
    rows = load_rows(cwd)
    ref = resolve_ref(rows, args.agent_id)
    if not ref:
        print("no runs recorded in this project's ledger yet")
        return 1
    append_event(cwd, {"type": "ok", "ref": ref, "ts": time.time()})
    print(f"marked {ref} ok (verified=true)")


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
    sub.add_parser("stats", help="agent x model table: runs, non-escalated%, escalated, wrong, median duration, tokens")

    p_why = sub.add_parser("why", help="why an agent is tiered the way it is, evidence permitting")
    p_why.add_argument("agent_type")
    p_why.add_argument("words", nargs="*")

    p_wrong = sub.add_parser("wrong", help="mark a delegated run wrong (verified=false)")
    p_wrong.add_argument("agent_id", help="an agent_id from the ledger, or 'last'")
    p_wrong.add_argument("why")

    p_ok = sub.add_parser("ok", help="mark a delegated run verified correct (verified=true)")
    p_ok.add_argument("agent_id", help="an agent_id from the ledger, or 'last'")

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
        "ok": cmd_ok,
        "off": cmd_off,
        "on": cmd_on,
        "mark-retune": cmd_mark_retune,
    }
    return handlers[args.command](args, cwd) or 0


if __name__ == "__main__":
    sys.exit(main())
