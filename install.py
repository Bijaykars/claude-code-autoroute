#!/usr/bin/env python
"""Install (or uninstall) AutoRoute's agents, hooks, CLAUDE.md section 0 and
settings.json hook wiring into ~/.claude. Stdlib only, Python 3.9+.

    python install.py                    # install (routing block only, on a fresh CLAUDE.md)
    python install.py --full-claude-md   # fresh install writes the whole CLAUDE.md instead
    python install.py --dry-run          # show what would happen, change nothing
    python install.py --uninstall
"""
import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME_CLAUDE = Path.home() / ".claude"
AGENTS_SRC = HERE / "agents"
HOOKS_SRC = HERE / "hooks"
CLAUDE_MD_SRC = HERE / "CLAUDE.md"
SETTINGS_EXAMPLE = HERE / "settings.example.json"
AUTOROUTE_CLI_SRC = HERE / "autoroute.py"
# hooks/hooks.json is the plugin manifest, not a hook script; a manual
# (non-plugin) install has no use for it in ~/.claude/hooks.
HOOKS_SKIP = {"hooks.json"}

MARK_START = "<!-- autoroute:start -->"
MARK_END = "<!-- autoroute:end -->"
BLOCK_RE = re.compile(re.escape(MARK_START) + r".*?" + re.escape(MARK_END) + r"\n?", re.DOTALL)


def ts():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def newest_backup(path):
    candidates = sorted(path.parent.glob(path.name + ".bak-*"))
    return candidates[-1] if candidates else None


def backup(path, dry_run, log):
    if not path.exists():
        return
    bak = path.with_name(path.name + f".bak-{ts()}")
    log.append(f"backup {path} -> {bak.name}")
    if not dry_run:
        shutil.copy2(path, bak)


def copy_files(src_dir, dst_dir, dry_run, log, skip=()):
    if not dst_dir.exists():
        log.append(f"mkdir {dst_dir}")
        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted(src_dir.glob("*")):
        if not f.is_file() or f.name in skip:
            continue
        dst = dst_dir / f.name
        backup(dst, dry_run, log)
        log.append(f"copy {f.name} -> {dst}")
        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)


def copy_one(src, dst_dir, dry_run, log):
    """Copy a single file (e.g. the autoroute.py CLI) into dst_dir, backing up
    anything it would overwrite first, same convention as copy_files."""
    dst = dst_dir / src.name
    backup(dst, dry_run, log)
    log.append(f"copy {src.name} -> {dst}")
    if not dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def restore_or_remove(dst, dry_run, log):
    if not dst.exists():
        return
    bak = newest_backup(dst)
    if bak:
        log.append(f"restore {bak.name} -> {dst}")
        if not dry_run:
            shutil.move(str(bak), str(dst))
    else:
        log.append(f"remove {dst}")
        if not dry_run:
            dst.unlink()


def uninstall_files(src_dir, dst_dir, dry_run, log, skip=()):
    if not dst_dir.exists():
        return
    for f in sorted(src_dir.glob("*")):
        if not f.is_file() or f.name in skip:
            continue
        restore_or_remove(dst_dir / f.name, dry_run, log)


def extract_section0(text):
    """Section 0 is '## 0. Cost routing' up to (not including) '## 1.'."""
    lines = text.splitlines(keepends=True)
    start = end = None
    for i, l in enumerate(lines):
        if start is None and l.startswith("## 0. Cost routing"):
            start = i
        elif start is not None and l.startswith("## 1."):
            end = i
            break
    if start is None:
        raise SystemExit("CLAUDE.md: could not find '## 0. Cost routing' section")
    if end is None:
        end = len(lines)
    # The source CLAUDE.md wraps section 0 in its own autoroute markers; strip
    # them here so callers can wrap the extracted text in fresh markers
    # without ending up with a duplicated MARK_END.
    body = [l for l in lines[start:end] if l.strip() not in (MARK_START, MARK_END)]
    return "".join(body).rstrip("\n") + "\n"


def install_claude_md(dry_run, log, full_claude_md):
    dst = HOME_CLAUDE / "CLAUDE.md"
    if not dst.exists():
        if full_claude_md:
            log.append(f"copy CLAUDE.md -> {dst} (new file, full copy, --full-claude-md)")
            if not dry_run:
                HOME_CLAUDE.mkdir(parents=True, exist_ok=True)
                shutil.copy2(CLAUDE_MD_SRC, dst)
        else:
            section0 = extract_section0(CLAUDE_MD_SRC.read_text(encoding="utf-8"))
            block = f"{MARK_START}\n{section0}{MARK_END}\n"
            log.append(f"write CLAUDE.md -> {dst} (new file, routing block only)")
            if not dry_run:
                HOME_CLAUDE.mkdir(parents=True, exist_ok=True)
                dst.write_text(block, encoding="utf-8")
        return

    section0 = extract_section0(CLAUDE_MD_SRC.read_text(encoding="utf-8"))
    block = f"{MARK_START}\n{section0}{MARK_END}\n"
    text = dst.read_text(encoding="utf-8")
    if BLOCK_RE.search(text):
        new_text = BLOCK_RE.sub(block, text)
        log.append(f"replace autoroute block in {dst}")
    else:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        new_text = text + sep + block
        log.append(f"append autoroute block to {dst}")
    backup(dst, dry_run, log)
    if not dry_run:
        dst.write_text(new_text, encoding="utf-8")


def uninstall_claude_md(dry_run, log):
    dst = HOME_CLAUDE / "CLAUDE.md"
    if not dst.exists():
        return
    text = dst.read_text(encoding="utf-8")
    if BLOCK_RE.search(text):
        remainder = BLOCK_RE.sub("", text)
        bak = newest_backup(dst)
        if not bak and not remainder.strip():
            # Fresh routing-block-only install: nothing existed before it and
            # nothing but the block remains, so remove the file rather than
            # leaving an empty CLAUDE.md.
            log.append(f"remove {dst} (fresh install, no prior file existed)")
            if not dry_run:
                dst.unlink()
        else:
            log.append(f"remove autoroute block from {dst}")
            if not dry_run:
                dst.write_text(remainder, encoding="utf-8")
    else:
        # No marker: either untouched by us, or it was a fresh full-copy install.
        bak = newest_backup(dst)
        if bak:
            log.append(f"restore {bak.name} -> {dst}")
            if not dry_run:
                shutil.move(str(bak), str(dst))
        else:
            log.append(f"remove {dst} (fresh install, no prior file existed)")
            if not dry_run:
                dst.unlink()


def hook_filename(command):
    m = re.search(r"([\w.-]+\.py)", command)
    return m.group(1) if m else None


def install_settings(dry_run, log):
    dst = HOME_CLAUDE / "settings.json"
    example = json.loads(SETTINGS_EXAMPLE.read_text(encoding="utf-8"))
    data = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
    hooks = data.setdefault("hooks", {})
    changed = False
    for event, entries in example["hooks"].items():
        existing = hooks.setdefault(event, [])
        for entry in entries:
            fnames = {hook_filename(h.get("command", "")) for h in entry.get("hooks", [])}
            already = any(
                hook_filename(h.get("command", "")) in fnames
                for e in existing
                for h in e.get("hooks", [])
            )
            if not already:
                existing.append(entry)
                changed = True
                log.append(f"add {event} hook entry ({', '.join(sorted(f for f in fnames if f))})")
    if changed:
        backup(dst, dry_run, log)
        log.append(f"write {dst}")
        if not dry_run:
            HOME_CLAUDE.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        log.append(f"{dst}: all three hooks already present, no change")


def uninstall_settings(dry_run, log):
    dst = HOME_CLAUDE / "settings.json"
    if not dst.exists():
        return
    our_names = {f.name for f in HOOKS_SRC.glob("*.py")}
    data = json.loads(dst.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})
    changed = False
    for event in list(hooks.keys()):
        kept = []
        for entry in hooks[event]:
            ours = any(hook_filename(h.get("command", "")) in our_names for h in entry.get("hooks", []))
            if ours:
                changed = True
                log.append(f"remove {event} hook entry")
            else:
                kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if changed:
        backup(dst, dry_run, log)
        log.append(f"write {dst}")
        if not dry_run:
            dst.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uninstall", action="store_true", help="remove what install.py added")
    ap.add_argument("--dry-run", action="store_true", help="print actions, change nothing")
    ap.add_argument(
        "--full-claude-md",
        action="store_true",
        help="on a fresh install with no existing ~/.claude/CLAUDE.md, write the "
        "complete CLAUDE.md (routing plus the coding-philosophy sections) "
        "instead of just the routing block",
    )
    args = ap.parse_args()

    log = []
    if args.uninstall:
        uninstall_files(AGENTS_SRC, HOME_CLAUDE / "agents", args.dry_run, log)
        uninstall_files(HOOKS_SRC, HOME_CLAUDE / "hooks", args.dry_run, log, skip=HOOKS_SKIP)
        restore_or_remove(HOME_CLAUDE / "hooks" / AUTOROUTE_CLI_SRC.name, args.dry_run, log)
        uninstall_settings(args.dry_run, log)
        uninstall_claude_md(args.dry_run, log)
        title = "AutoRoute uninstall"
    else:
        copy_files(AGENTS_SRC, HOME_CLAUDE / "agents", args.dry_run, log)
        copy_files(HOOKS_SRC, HOME_CLAUDE / "hooks", args.dry_run, log, skip=HOOKS_SKIP)
        copy_one(AUTOROUTE_CLI_SRC, HOME_CLAUDE / "hooks", args.dry_run, log)
        install_claude_md(args.dry_run, log, args.full_claude_md)
        install_settings(args.dry_run, log)
        title = "AutoRoute install"

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}{title}: {len(log)} action(s)")
    for line in log:
        print(f"  {prefix}{line}")
    if not log:
        print("  (nothing to do)")


if __name__ == "__main__":
    sys.exit(main())
