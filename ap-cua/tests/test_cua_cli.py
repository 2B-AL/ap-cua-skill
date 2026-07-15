import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import cua  # noqa: E402


class FakeSession:
    def __init__(self):
        self.last_invocation_id = None

    def set_last_invocation_id(self, value):
        self.last_invocation_id = value


class CuaWaitBudgetTests(unittest.TestCase):
    def test_delegate_rejects_negative_budget_before_creating_task(self):
        with (
            mock.patch.object(cua, "resolve_base_url", return_value="http://gateway"),
            mock.patch.object(cua.cua_auth, "authorized_call") as call,
            self.assertRaises(cua.SkillError) as ctx,
        ):
            cua.cmd_delegate(
                Namespace(objective="test", wait_ms=-1),
                state=object(),
                session=FakeSession(),
            )

        self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")
        call.assert_not_called()

    def test_watch_splits_total_budget_into_server_sized_chunks(self):
        responses = [
            {"invocation_id": "task-1", "outcome": "in_progress"},
            {"invocation_id": "task-1", "outcome": "in_progress"},
            {"invocation_id": "task-1", "outcome": "completed"},
        ]
        session = FakeSession()
        with (
            mock.patch.object(cua, "resolve_base_url", return_value="http://gateway"),
            mock.patch.object(cua.cua_auth, "authorized_call", side_effect=responses) as call,
        ):
            result = cua.cmd_watch(
                Namespace(invocation_id="task-1", last=False, wait_ms=125000),
                state=object(),
                session=session,
            )

        self.assertEqual(result["data"]["outcome"], "completed")
        self.assertEqual([item.kwargs["body"]["wait_ms"] for item in call.call_args_list], [60000, 60000, 5000])
        self.assertEqual([item.kwargs["timeout"] for item in call.call_args_list], [90, 90, 35])

    def test_zero_budget_checks_without_server_long_poll(self):
        session = FakeSession()
        with (
            mock.patch.object(cua, "resolve_base_url", return_value="http://gateway"),
            mock.patch.object(
                cua.cua_auth,
                "authorized_call",
                return_value={"invocation_id": "task-1", "outcome": "in_progress"},
            ) as call,
        ):
            cua.cmd_watch(
                Namespace(invocation_id="task-1", last=False, wait_ms=0),
                state=object(),
                session=session,
            )

        self.assertEqual(call.call_args.args[2:4], ("GET", "/v1/invocations/task-1"))

    def test_delegate_creates_once_then_uses_watch_budget(self):
        responses = [
            {"invocation_id": "task-1", "outcome": "in_progress"},
            {"invocation_id": "task-1", "outcome": "completed"},
        ]
        session = FakeSession()
        with (
            mock.patch.object(cua, "resolve_base_url", return_value="http://gateway"),
            mock.patch.object(cua.cua_auth, "authorized_call", side_effect=responses) as call,
        ):
            result = cua.cmd_delegate(
                Namespace(objective="test", wait_ms=900000),
                state=object(),
                session=session,
            )

        self.assertEqual(result["data"]["outcome"], "completed")
        self.assertEqual(call.call_args_list[0].args[2:4], ("POST", "/v1/invocations"))
        self.assertEqual(call.call_args_list[0].kwargs["body"]["wait_ms"], 0)
        self.assertEqual(call.call_args_list[1].args[2:4], ("POST", "/v1/invocations/task-1/watch"))
        self.assertEqual(call.call_args_list[1].kwargs["body"]["wait_ms"], 60000)


if __name__ == "__main__":
    unittest.main()
