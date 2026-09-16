"""Subprocess tests for hooks/retune-due.py, hooks/inline-counter.py and
hooks/prompt-nudge.py. Stdlib unittest only.

Run: python -m unittest tests/test_hooks.py -v
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / "hooks"


def run_hook(script, payload=None, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    stdin = json.dumps(payload) if payload is not None else ""
    result = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


class RetuneDueTests(unittest.TestCase):
    def _write_memory(self, tmp, agent, body):
        d = Path(tmp) / ".claude" / "agent-memory" / agent
        d.mkdir(parents=True, exist_ok=True)
        (d / "MEMORY.md").write_text(body, encoding="utf-8")

    def test_counts_only_rows_after_last_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Ten OLD rows above the marker must never be recounted.
            old_rows = "\n".join(
                f"| 2026-01-{i:02d} | old task | resolved | sonnet |" for i in range(1, 11)
            )
            body = (
                "# agent memory\n\n"
                "| date | task shape | resolved or escalated | model used |\n"
                "|---|---|---|---|\n"
                f"{old_rows}\n\n"
                "## Retune 2026-01-10 — rung 4→5 (sonnet/medium -> sonnet/high) "
                "· baseline N=0 F=0 rate=n/a · owner · verify next run\n\n"
                "| date | task shape | resolved or escalated | model used |\n"
                "|---|---|---|---|\n"
                "| 2026-01-11 | new task | resolved | sonnet |\n"
            )
            self._write_memory(tmp, "someagent", body)
            out = run_hook("retune-due.py", {"cwd": tmp})
            self.assertEqual(out, "", "only 1 row after the marker; must not fire")

    def test_wrong_five_cell_row_and_multiplier_fold(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = (
                "# agent memory\n\n"
                "## Retune 2026-01-10 — rung 4→5 · baseline N=0 F=0 rate=n/a · owner · verify next run\n\n"
                "| date | task shape | resolved or escalated | model used |\n"
                "|---|---|---|---|\n"
                "| 2026-01-11 | task a | resolved ×3 | sonnet |\n"
                "| 2026-01-12 | task b | WRONG | sonnet | root cause disproven |\n"
                "| 2026-01-13 | task c | WRONG | sonnet | edit redone |\n"
                "| 2026-01-14 | task d | WRONG | sonnet | test failed |\n"
            )
            self._write_memory(tmp, "someagent", body)
            out = run_hook("retune-due.py", {"cwd": tmp})
            self.assertIn("someagent", out)
            self.assertIn("N=3", out)
            self.assertIn("F=3", out)
            self.assertIn("fail_rate=1.00", out)


class InlineCounterTests(unittest.TestCase):
    def _counter_path(self, sid):
        return Path(tempfile.gettempdir()) / f"delegate-count-{sid}"

    def setUp(self):
        self.sid = "test" + uuid.uuid4().hex[:8]
        self.counter = self._counter_path(self.sid)
        if self.counter.exists():
            self.counter.unlink()

    def tearDown(self):
        if self.counter.exists():
            self.counter.unlink()

    def test_ignores_subagent_payloads(self):
        run_hook("inline-counter.py", {"tool_name": "Read", "session_id": self.sid})
        self.assertEqual(self.counter.read_text().strip(), "1")

        for key in ("agent_id", "agent_type", "subagent_id", "parent_session_id"):
            run_hook("inline-counter.py", {"tool_name": "Read", "session_id": self.sid, key: "x"})
            self.assertEqual(
                self.counter.read_text().strip(), "1",
                f"a payload carrying {key} must not advance the parent's counter",
            )

    def test_agent_tool_resets_streak(self):
        for _ in range(3):
            run_hook("inline-counter.py", {"tool_name": "Read", "session_id": self.sid})
        self.assertEqual(self.counter.read_text().strip(), "3")
        run_hook("inline-counter.py", {"tool_name": "Agent", "session_id": self.sid})
        self.assertEqual(self.counter.read_text().strip(), "0")


class PromptNudgeTests(unittest.TestCase):
    def test_default_tripwire(self):
        env = dict(os.environ)
        env.pop("DELEGATE_TRIPWIRE", None)
        result = subprocess.run(
            [sys.executable, str(HOOKS / "prompt-nudge.py")],
            input="", capture_output=True, text=True, env=env,
        )
        data = json.loads(result.stdout.strip())
        msg = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Before the 4th consecutive inline", msg)

    def test_custom_tripwire(self):
        out = run_hook("prompt-nudge.py", payload=None, env_extra={"DELEGATE_TRIPWIRE": "7"})
        data = json.loads(out)
        msg = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Before the 7th consecutive inline", msg)

    def test_off_switch_replaces_reminder(self):
        with tempfile.TemporaryDirectory() as fake_home:
            (Path(fake_home) / ".claude" / "autoroute").mkdir(parents=True)
            (Path(fake_home) / ".claude" / "autoroute" / "off").touch()
            out = run_hook("prompt-nudge.py", env_extra={"HOME": fake_home, "USERPROFILE": fake_home})
            data = json.loads(out)
            msg = data["hookSpecificOutput"]["additionalContext"]
            self.assertIn("OFF", msg)
            self.assertIn("do not delegate", msg)

    def test_plugin_root_appends_summary(self):
        env = dict(os.environ)
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        out = run_hook("prompt-nudge.py", env_extra={"CLAUDE_PLUGIN_ROOT": "/fake/plugin/root"})
        data = json.loads(out)
        msg = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Routing (plugin mode", msg)


class LedgerHookTests(unittest.TestCase):
    """PreToolUse(Agent) -> SubagentStart -> SubagentStop, hooks/ledger.py."""

    def _write_transcript(self, tmp, model, is_error, final_text):
        path = Path(tmp) / "transcript.jsonl"
        lines = [
            {"type": "assistant", "message": {"model": model,
             "usage": {"input_tokens": 1000, "output_tokens": 200},
             "content": [{"type": "text", "text": "working on it"}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "boom", "is_error": is_error}
            ]}},
            {"type": "not-a-message-at-all"},
            {"type": "assistant", "message": {"model": model,
             "usage": {"input_tokens": 500, "output_tokens": 50},
             "content": [{"type": "text", "text": final_text}]}},
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
            f.write("not even json\n")  # tolerated garbage line
        return str(path)

    def _write_agent_frontmatter(self, tmp, agent_type, model, effort):
        d = Path(tmp) / ".claude" / "agents"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{agent_type}.md").write_text(
            f"---\nname: {agent_type}\nmodel: {model}\neffort: {effort}\n---\nbody\n",
            encoding="utf-8",
        )

    def _run_flow(self, tmp, session_id, agent_id, agent_type, description, transcript_path, escalated):
        pre = {
            "hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": session_id, "cwd": tmp,
            "tool_input": {"subagent_type": agent_type, "description": description,
                           "prompt": "x" * 250, "model": None},
        }
        run_hook("ledger.py", pre)

        start = {"hook_event_name": "SubagentStart", "session_id": session_id, "cwd": tmp,
                  "agent_id": agent_id, "agent_type": agent_type}
        run_hook("ledger.py", start)

        stop = {"hook_event_name": "SubagentStop", "session_id": session_id, "cwd": tmp,
                "agent_id": agent_id, "agent_type": agent_type, "agent_transcript_path": transcript_path}
        run_hook("ledger.py", stop)

    def test_end_to_end_escalated(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_agent_frontmatter(tmp, "implement", "sonnet", "high")
            transcript = self._write_transcript(
                tmp, "claude-sonnet-5", True,
                "ESCALATE: cannot finish\nTRIED: read the file\nNEXT: model:opus/medium\n",
            )
            self._run_flow(tmp, "sess1", "agent-1", "implement", "fix parser bug", transcript, True)

            pending = Path(tmp) / ".claude" / "autoroute" / "pending.jsonl"
            self.assertFalse(pending.exists() and pending.read_text().strip(), "pending entry must be consumed")

            active_file = Path(tmp) / ".claude" / "autoroute" / "active" / "agent-1.json"
            self.assertFalse(active_file.exists(), "active entry must be consumed (deleted) on stop")

            ledger_lines = (Path(tmp) / ".claude" / "autoroute" / "ledger.jsonl").read_text().splitlines()
            self.assertEqual(len(ledger_lines), 1)
            event = json.loads(ledger_lines[0])
            self.assertEqual(event["type"], "run")
            self.assertEqual(event["agent_id"], "agent-1")
            self.assertEqual(event["agent_type"], "implement")
            self.assertEqual(event["task"], "fix parser bug")
            self.assertEqual(event["model"], "claude-sonnet-5")
            self.assertEqual(event["model_tier"], "sonnet")
            self.assertEqual(event["configured_model"], "sonnet")
            self.assertEqual(event["configured_effort"], "high")
            self.assertEqual(event["outcome"], "escalated")
            self.assertIsNone(event["verified"])
            self.assertEqual(event["next"], "model:opus/medium")
            self.assertEqual(event["tool_errors"], 1)
            self.assertEqual(event["tokens"], {"input": 1500, "output": 250})
            self.assertIsNotNone(event["duration_s"])
            self.assertFalse(event["wrong"])

    def test_end_to_end_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_agent_frontmatter(tmp, "implement", "sonnet", "high")
            transcript = self._write_transcript(tmp, "claude-sonnet-5", False, "All done, tests green.")
            self._run_flow(tmp, "sess2", "agent-2", "implement", "add validation", transcript, False)

            ledger_lines = (Path(tmp) / ".claude" / "autoroute" / "ledger.jsonl").read_text().splitlines()
            event = json.loads(ledger_lines[0])
            self.assertEqual(event["outcome"], "resolved")
            self.assertIsNone(event["next"])
            self.assertEqual(event["tool_errors"], 0)

    def test_off_switch_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as fake_home:
            (Path(fake_home) / ".claude" / "autoroute").mkdir(parents=True)
            (Path(fake_home) / ".claude" / "autoroute" / "off").touch()
            pre = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": "s", "cwd": tmp,
                   "tool_input": {"subagent_type": "implement", "description": "d", "prompt": "p"}}
            run_hook("ledger.py", pre, env_extra={"HOME": fake_home, "USERPROFILE": fake_home})
            self.assertFalse((Path(tmp) / ".claude" / "autoroute").exists())

    def test_malformed_payload_does_not_crash(self):
        result = subprocess.run(
            [sys.executable, str(HOOKS / "ledger.py")],
            input="not json at all", capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_parallel_starts_stops_out_of_order(self):
        """Three PreToolUse/SubagentStart pairs on the same session, then
        SubagentStop calls in a different order than the starts. Each ledger
        row must still carry its own task, and nothing may crash -- this is
        the per-agent-file active/ directory replacing the single
        active.json that a concurrent start/stop could race on."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write_agent_frontmatter(tmp, "implement", "sonnet", "high")
            session_id = "sessP"
            agent_ids = ["p0", "p1", "p2"]
            descriptions = ["task-0", "task-1", "task-2"]
            for desc in descriptions:
                pre = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": session_id,
                       "cwd": tmp, "tool_input": {"subagent_type": "implement", "description": desc,
                                                   "prompt": "x", "model": None}}
                run_hook("ledger.py", pre)
            for agent_id in agent_ids:
                start = {"hook_event_name": "SubagentStart", "session_id": session_id, "cwd": tmp,
                         "agent_id": agent_id, "agent_type": "implement"}
                run_hook("ledger.py", start)

            transcripts = {
                agent_id: self._write_transcript(tmp, "claude-sonnet-5", False, f"done {agent_id}")
                for agent_id in agent_ids
            }
            for agent_id in ["p1", "p0", "p2"]:  # deliberately out of start order
                stop = {"hook_event_name": "SubagentStop", "session_id": session_id, "cwd": tmp,
                        "agent_id": agent_id, "agent_type": "implement",
                        "agent_transcript_path": transcripts[agent_id]}
                run_hook("ledger.py", stop)

            ledger_lines = (Path(tmp) / ".claude" / "autoroute" / "ledger.jsonl").read_text().splitlines()
            self.assertEqual(len(ledger_lines), 3)
            events = [json.loads(l) for l in ledger_lines]
            tasks = sorted(e["task"] for e in events)
            self.assertEqual(tasks, descriptions, "each run must get some task, none lost or duplicated")
            for agent_id in agent_ids:
                self.assertFalse(
                    (Path(tmp) / ".claude" / "autoroute" / "active" / f"{agent_id}.json").exists()
                )

    def test_orphan_stop_no_start(self):
        """SubagentStop with no matching SubagentStart on record must still
        write a ledger row (duration/task null) instead of crashing."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = self._write_transcript(tmp, "claude-sonnet-5", False, "done")
            stop = {"hook_event_name": "SubagentStop", "session_id": "sess-orphan", "cwd": tmp,
                    "agent_id": "orphan-1", "agent_type": "implement", "agent_transcript_path": transcript}
            run_hook("ledger.py", stop)

            ledger_lines = (Path(tmp) / ".claude" / "autoroute" / "ledger.jsonl").read_text().splitlines()
            self.assertEqual(len(ledger_lines), 1)
            event = json.loads(ledger_lines[0])
            self.assertEqual(event["agent_id"], "orphan-1")
            self.assertIsNone(event["task"])
            self.assertIsNone(event["duration_s"])

    def test_concurrent_subagent_starts_do_not_lose_or_duplicate_pending(self):
        """10 pending entries for the same session/agent_type, 10 real
        SubagentStart hook PROCESSES fired at the same instant (distinct
        agent_ids). Without a lock around pop_pending's read -> choose ->
        rewrite, two processes can read pending.jsonl before either rewrites
        it and both match the same entry, losing one task and duplicating
        another. Repeated 3x in-test to catch flakiness."""
        agent_ids = [f"c{i}" for i in range(10)]
        for attempt in range(3):
            with tempfile.TemporaryDirectory() as tmp:
                session_id = f"race-{attempt}"
                pending_path = Path(tmp) / ".claude" / "autoroute" / "pending.jsonl"
                pending_path.parent.mkdir(parents=True, exist_ok=True)
                descriptions = [f"race-task-{attempt}-{i}" for i in range(10)]
                with open(pending_path, "w", encoding="utf-8") as f:
                    for desc in descriptions:
                        f.write(json.dumps({
                            "session_id": session_id, "subagent_type": "implement",
                            "description": desc, "model_override": None, "prompt_head": desc,
                        }) + "\n")

                procs = []
                for agent_id in agent_ids:
                    payload = json.dumps({
                        "hook_event_name": "SubagentStart", "session_id": session_id,
                        "cwd": tmp, "agent_id": agent_id, "agent_type": "implement",
                    })
                    p = subprocess.Popen(
                        [sys.executable, str(HOOKS / "ledger.py")],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True,
                    )
                    procs.append((p, payload))
                for p, payload in procs:
                    p.stdin.write(payload)
                    p.stdin.close()
                for p, _ in procs:
                    p.wait(timeout=30)
                    p.stdout.close()
                    p.stderr.close()

                active_dir = Path(tmp) / ".claude" / "autoroute" / "active"
                found = []
                for agent_id in agent_ids:
                    active_file = active_dir / f"{agent_id}.json"
                    self.assertTrue(active_file.exists(), f"attempt {attempt}: missing {active_file}")
                    found.append(json.loads(active_file.read_text())["description"])

                self.assertEqual(
                    sorted(found), sorted(descriptions),
                    f"attempt {attempt}: 10 SubagentStart hooks must resolve to 10 distinct, "
                    f"unduplicated pending descriptions",
                )
                remaining = [l for l in pending_path.read_text().splitlines() if l.strip()]
                self.assertEqual(remaining, [], f"attempt {attempt}: pending.jsonl must be fully drained")


class RetuneDueJsonlTests(unittest.TestCase):
    def _write_ledger(self, tmp, events):
        d = Path(tmp) / ".claude" / "autoroute"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "ledger.jsonl", "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_jsonl_only_fires_retune_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": f"a{i}", "outcome": "resolved"}
                for i in range(9)
            ] + [{"type": "run", "agent_type": "implement", "agent_id": "a9", "outcome": "escalated"}]
            self._write_ledger(tmp, events)
            out = run_hook("retune-due.py", {"cwd": tmp})
            self.assertIn("implement", out)
            self.assertIn("N=10", out)
            self.assertIn("F=1", out)

    def test_jsonl_respects_retune_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": f"a{i}", "outcome": "resolved"}
                for i in range(10)
            ] + [{"type": "retune", "agent": "implement", "note": "bumped"},
                 {"type": "run", "agent_type": "implement", "agent_id": "b0", "outcome": "resolved"}]
            self._write_ledger(tmp, events)
            out = run_hook("retune-due.py", {"cwd": tmp})
            self.assertEqual(out, "", "only 1 row after the marker; must not fire")

    def test_wrong_event_flips_a_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": f"a{i}", "outcome": "resolved"}
                for i in range(3)
            ] + [{"type": "wrong", "ref": "a0"}, {"type": "wrong", "ref": "a1"}, {"type": "wrong", "ref": "a2"}]
            self._write_ledger(tmp, events)
            out = run_hook("retune-due.py", {"cwd": tmp})
            self.assertIn("implement", out)
            self.assertIn("N=3", out)
            self.assertIn("F=3", out)

    def test_larger_source_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            # MEMORY.md has 2 rows; ledger.jsonl has 10 -> ledger must be reported.
            d = Path(tmp) / ".claude" / "agent-memory" / "implement"
            d.mkdir(parents=True, exist_ok=True)
            (d / "MEMORY.md").write_text(
                "| date | task shape | resolved or escalated | model used |\n|---|---|---|---|\n"
                "| 2026-01-01 | a | resolved | sonnet |\n| 2026-01-02 | b | resolved | sonnet |\n",
                encoding="utf-8",
            )
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": f"a{i}", "outcome": "resolved"}
                for i in range(10)
            ]
            self._write_ledger(tmp, events)
            out = run_hook("retune-due.py", {"cwd": tmp})
            self.assertIn("N=10", out, "the ledger has more rows than MEMORY.md and must win")


class AutorouteCliTests(unittest.TestCase):
    def run_cli(self, args, cwd, env_extra=None):
        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            [sys.executable, str(REPO / "autoroute.py"), *args],
            capture_output=True, text=True, cwd=cwd, env=env,
        )
        return result

    def _write_ledger(self, tmp, events):
        d = Path(tmp) / ".claude" / "autoroute"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "ledger.jsonl", "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return d / "ledger.jsonl"

    def test_status_reports_runs_and_retune_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": f"a{i}",
                 "outcome": "resolved" if i else "escalated", "model": "claude-sonnet-5",
                 "tokens": {"input": 100, "output": 20}, "duration_s": 10.0}
                for i in range(10)
            ]
            self._write_ledger(tmp, events)
            result = self.run_cli(["status"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("implement", result.stdout)
            self.assertIn("RETUNE DUE", result.stdout)

    def test_stats_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": "a1", "outcome": "resolved",
                 "model": "claude-sonnet-5", "tokens": {"input": 100, "output": 20}, "duration_s": 5.0,
                 "ts": time.time()},
            ]
            self._write_ledger(tmp, events)
            result = self.run_cli(["stats"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("All time", result.stdout)
            self.assertIn("Last 30 days", result.stdout)
            self.assertIn("implement", result.stdout)

    def test_why_insufficient_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": "a1", "outcome": "resolved",
                 "model": "claude-sonnet-5", "task": "fix the parser"},
            ]
            self._write_ledger(tmp, events)
            result = self.run_cli(["why", "implement"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("insufficient data (N=1)", result.stdout)
            self.assertIn("Objective:", result.stdout)

    def test_why_task_words_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": "a1", "outcome": "resolved",
                 "model": "claude-sonnet-5", "task": "fix the parser bug"},
                {"type": "run", "agent_type": "implement", "agent_id": "a2", "outcome": "resolved",
                 "model": "claude-sonnet-5", "task": "add a button"},
            ]
            self._write_ledger(tmp, events)
            result = self.run_cli(["why", "implement", "parser"], tmp)
            self.assertIn("Matching task words", result.stdout)

    def test_wrong_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": "a1", "outcome": "resolved"},
                {"type": "run", "agent_type": "implement", "agent_id": "a2", "outcome": "resolved"},
            ]
            ledger = self._write_ledger(tmp, events)
            result = self.run_cli(["wrong", "last", "root cause disproven"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = ledger.read_text().splitlines()
            last = json.loads(lines[-1])
            self.assertEqual(last["type"], "wrong")
            self.assertEqual(last["ref"], "a2")

    def test_ok_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": "a1", "outcome": "resolved"},
            ]
            ledger = self._write_ledger(tmp, events)
            result = self.run_cli(["ok", "last"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            last = json.loads(ledger.read_text().splitlines()[-1])
            self.assertEqual(last["type"], "ok")
            self.assertEqual(last["ref"], "a1")

    def test_why_prints_cost_line_when_all_verified(self):
        """Regression for the tier-normalisation bug: real model ids like
        claude-sonnet-5/claude-opus-5 must be bucketed by tier so the
        BLENDED_PER_M lookup (keyed by tier) actually hits. The cost line
        only prints once every tier present has >= 10 VERIFIED (ok/wrong)
        rows -- resolved-but-unverified rows are not enough."""
        with tempfile.TemporaryDirectory() as tmp:
            events = (
                [{"type": "run", "agent_type": "implement", "agent_id": f"s{i}", "outcome": "resolved",
                  "model": "claude-sonnet-5", "tokens": {"input": 800, "output": 200}}
                 for i in range(10)]
                + [{"type": "run", "agent_type": "implement", "agent_id": f"o{i}", "outcome": "resolved",
                    "model": "claude-opus-5", "tokens": {"input": 800, "output": 200}}
                   for i in range(10)]
                + [{"type": "ok", "ref": f"s{i}"} for i in range(10)]
                + [{"type": "ok", "ref": f"o{i}"} for i in range(10)]
            )
            self._write_ledger(tmp, events)
            result = self.run_cli(["why", "implement"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("sonnet: N=10", result.stdout)
            self.assertIn("opus: N=10", result.stdout)
            self.assertIn("expected cost to verified success", result.stdout)
            self.assertNotIn("no token data", result.stdout)
            self.assertNotIn("not available", result.stdout)

    def test_why_cost_not_available_without_verification(self):
        """Same shape as above (10 resolved rows per tier) but NONE of them
        verified via ok/wrong -- the non-escalated proxy alone must never
        produce a cost figure."""
        with tempfile.TemporaryDirectory() as tmp:
            events = (
                [{"type": "run", "agent_type": "implement", "agent_id": f"s{i}", "outcome": "resolved",
                  "model": "claude-sonnet-5", "tokens": {"input": 800, "output": 200}}
                 for i in range(10)]
                + [{"type": "run", "agent_type": "implement", "agent_id": f"o{i}", "outcome": "resolved",
                    "model": "claude-opus-5", "tokens": {"input": 800, "output": 200}}
                   for i in range(10)]
            )
            self._write_ledger(tmp, events)
            result = self.run_cli(["why", "implement"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Expected cost to verified success: not available", result.stdout)
            self.assertIn("have opus=0, sonnet=0", result.stdout)
            self.assertNotIn("$", result.stdout)

    def test_why_no_cost_line_when_insufficient_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"type": "run", "agent_type": "implement", "agent_id": f"s{i}", "outcome": "resolved",
                 "model": "claude-sonnet-5", "tokens": {"input": 800, "output": 200}}
                for i in range(9)
            ]
            self._write_ledger(tmp, events)
            result = self.run_cli(["why", "implement"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("insufficient data (N=9)", result.stdout)
            self.assertNotIn("$", result.stdout)
            self.assertIn("not available", result.stdout)

    def test_off_on_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as fake_home:
            env = {"HOME": fake_home, "USERPROFILE": fake_home}
            off_flag = Path(fake_home) / ".claude" / "autoroute" / "off"

            r = self.run_cli(["off"], tmp, env_extra=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(off_flag.exists())
            self.assertIn("OFF", r.stdout)

            r = self.run_cli(["on"], tmp, env_extra=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(off_flag.exists())
            self.assertIn("ON", r.stdout)

    def test_mark_retune_appends_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self._write_ledger(tmp, [])
            result = self.run_cli(["mark-retune", "implement", "sonnet/high -> sonnet/xhigh"], tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            last = json.loads(ledger.read_text().splitlines()[-1])
            self.assertEqual(last["type"], "retune")
            self.assertEqual(last["agent"], "implement")


if __name__ == "__main__":
    unittest.main()
