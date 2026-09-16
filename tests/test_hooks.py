"""Subprocess tests for hooks/retune-due.py, hooks/inline-counter.py and
hooks/prompt-nudge.py. Stdlib unittest only.

Run: python -m unittest tests/test_hooks.py -v
"""
import json
import os
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
