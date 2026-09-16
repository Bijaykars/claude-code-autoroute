# SessionStart hook: flag agents whose ledger has enough new rows since their last
# "## Retune" marker for retune to judge. Silent when nothing is due or on any error.
import json, os, re, sys, glob
try:
    p = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    cwd = p.get("cwd") or os.getcwd()
    ROW = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|[^|]*\|\s*([^|]*?)\s*\|")
    MULT = re.compile(r"[×x]\s*(\d+)")
    due = []
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
        if n >= 10 or w >= 3:
            rate = f"{(e + w) / n:.2f}" if n else "n/a"
            due.append(f"{agent}: N={n} F={e + w} fail_rate={rate}")
    if due:
        msg = ("[retune] RETUNE DUE - " + "; ".join(due) +
               ". Launch the `retune` agent in the background before other work.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))
except Exception:
    pass
