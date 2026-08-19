import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import cua  # noqa: E402


class CuaBundledConfigTests(unittest.TestCase):
    def test_bundled_base_url_targets_production_gateway(self):
        self.assertEqual(
            cua.bundled_base_url(),
            "https://s4ebmnro55svp3n2okb3k.apigateway-cn-beijing.volceapi.com",
        )


class FakeSession:
    def __init__(self):
        self.last_invocation_id = None
        self.last_task_id = None
        self.last_context_id = None

    def set_last_invocation_id(self, value):
        self.last_invocation_id = value

    def set_last(self, **values):
        for key, value in values.items():
            if value:
                setattr(self, key, value)


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

    def test_delegate_preserves_create_time_security_advisory_while_waiting(self):
        advisory = {
            "url": "https://security.example.test/security/view#ticket=sv_test",
            "expires_at": "2026-08-19T12:00:00Z",
        }
        responses = [
            {
                "invocation_id": "task-1",
                "outcome": "in_progress",
                "platform": {"security_advisory": advisory},
            },
            {"invocation_id": "task-1", "outcome": "completed", "platform": {}},
        ]
        session = FakeSession()
        with (
            mock.patch.object(cua, "resolve_base_url", return_value="http://gateway"),
            mock.patch.object(cua.cua_auth, "authorized_call", side_effect=responses),
        ):
            result = cua.cmd_delegate(
                Namespace(objective="test", wait_ms=60000),
                state=object(),
                session=session,
            )

        self.assertEqual(result["data"]["platform"]["security_advisory"], advisory)
        self.assertIn("Surface that URL to the user once", result["next"]["agent_hint"])
        self.assertIn("continue the task workflow normally", result["next"]["agent_hint"])

    def test_task_next_hint_surfaces_security_advisory_without_changing_outcome(self):
        next_step = cua._next_for_task({
            "invocation_id": "task-1",
            "outcome": "in_progress",
            "platform": {
                "security_advisory": {
                    "url": "https://security.example.test/security/view#ticket=sv_test",
                },
            },
        })

        self.assertIn("task status --task-id task-1", next_step["command"])
        self.assertIn("security advisory", next_step["agent_hint"])
        self.assertNotIn("sv_test", next_step["agent_hint"])

    def test_task_run_uses_v1_tasks_and_surfaces_advisory(self):
        envelope = {
            "invocation_id": "task-1",
            "outcome": "in_progress",
            "platform": {
                "context_id": "ctx-1",
                "security_advisory": {
                    "url": "https://security.example.test/security/view#ticket=sv_test",
                    "expires_at": "2026-08-19T12:00:00Z",
                },
            },
        }
        session = FakeSession()
        with (
            mock.patch.object(cua, "resolve_base_url", return_value="http://gateway"),
            mock.patch.object(cua.cua_auth, "authorized_call", return_value=envelope) as call,
        ):
            result = cua.cmd_task_run(
                Namespace(
                    objective="test",
                    wait_ms=0,
                    desktop=None,
                    title=None,
                    disable_ask_user=False,
                ),
                state=object(),
                session=session,
            )

        self.assertEqual(call.call_args.args[2:4], ("POST", "/v1/tasks"))
        self.assertEqual(call.call_args.kwargs["body"], {"objective": "test", "wait_ms": 0})
        self.assertEqual(result["data"]["platform"]["security_advisory"], envelope["platform"]["security_advisory"])
        self.assertIn("task status --task-id task-1", result["next"]["command"])
        self.assertEqual(session.last_task_id, "task-1")
        self.assertEqual(session.last_context_id, "ctx-1")


if __name__ == "__main__":
    unittest.main()
