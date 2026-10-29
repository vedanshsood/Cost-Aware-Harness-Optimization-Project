"""Test the idle guard and recovery reminder without model calls."""

import asyncio
from unittest.mock import AsyncMock, patch

from harness.bounded_agent import (
    BoundedTerminus2,
    IdleResponseLimitReached,
)
from harness.recovery_agent import RecoveryTerminus2


def response(commands=None, complete=False, feedback=""):
    """Match the parent's six-item return value."""
    return (
        commands if commands is not None else [],
        complete,
        feedback,
        "Example analysis",
        "Example plan",
        object(),
    )


async def interact(agent):
    return await agent._handle_llm_interaction(
        chat=None,
        prompt="Test",
        logging_paths=(None, None, None),
    )


async def main():
    # Bypass initialization so no model client is constructed.
    agent = object.__new__(BoundedTerminus2)
    agent._idle_response_count = 0
    agent._recovery_reminders_sent = 0
    agent._action_after_reminder = False
    agent._completion_after_reminder = False
    agent._stopped_by_idle_guard = False

    parent = AsyncMock(return_value=response())

    with patch.object(
        RecoveryTerminus2,
        "_handle_llm_interaction",
        parent,
    ):
        # Three idle responses are allowed and counted.
        for expected in range(1, 4):
            await interact(agent)
            assert agent._idle_response_count == expected

        assert parent.await_count == 3

        # The first two requests must remain unchanged.
        for call in parent.await_args_list[:2]:
            assert call.kwargs["prompt"] == "Test"

        # Only the third request receives the recovery reminder.
        third_prompt = parent.await_args_list[2].kwargs["prompt"]
        assert third_prompt.startswith("Test")
        assert "Harness notice:" in third_prompt
        assert agent._recovery_reminders_sent == 1

        print("[OK] Reminder appears on the third request only.")
        print("[OK] Original observation is preserved.")

        # Stop before asking the parent for a fourth response.
        try:
            await interact(agent)
        except IdleResponseLimitReached:
            pass
        else:
            raise AssertionError("Guard did not stop the idle loop.")

        assert parent.await_count == 3
        print("[OK] Stops after three idle responses; no fourth call.")

        # Each of these must reset the idle counter.
        cases = [
            (
                "Command execution resets the counter",
                response(commands=[object()]),
            ),
            (
                "Completion request resets the counter",
                response(complete=True),
            ),
            (
                "Parser feedback resets the counter",
                response(feedback="ERROR: Invalid response"),
            ),
        ]

        for label, result in cases:
            agent._idle_response_count = 2
            parent.return_value = result

            returned = await interact(agent)

            assert agent._idle_response_count == 0
            assert returned is result
            print(f"[OK] {label}.")

        assert agent._action_after_reminder is True
        assert agent._completion_after_reminder is True
        print("[OK] Activity after the reminder is recorded.")

        # A waiting command must not count as an idle response.
        class WaitCommand:
            keystrokes = ""
            duration_sec = 10

        agent._idle_response_count = 2
        parent.return_value = response(commands=[WaitCommand()])

        await interact(agent)

        assert agent._idle_response_count == 0
        print("[OK] A waiting command is not treated as idle.")

    # A later idle streak must not send another reminder.
    agent._idle_response_count = 0
    parent.reset_mock()
    parent.return_value = response()

    with patch.object(
        RecoveryTerminus2,
        "_handle_llm_interaction",
        parent,
    ):
        for expected in range(1, 4):
            await interact(agent)
            assert agent._idle_response_count == expected

        assert parent.await_count == 3
        assert agent._recovery_reminders_sent == 1

        for call in parent.await_args_list:
            assert call.kwargs["prompt"] == "Test"

        try:
            await interact(agent)
        except IdleResponseLimitReached:
            pass
        else:
            raise AssertionError("Later idle streak did not stop.")

        assert parent.await_count == 3
        print("[OK] Reminder is limited to once per task.")
        print("[OK] A later idle streak still triggers the stop rule.")

    print("\nAll idle-response guard checks passed.")
    print("No model client, model calls, or task attempts were used.")


if __name__ == "__main__":
    asyncio.run(main())