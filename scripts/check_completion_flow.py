"""Test output validators and harness integration without model calls.

Uses temporary synthetic fixtures and mocked agent/transport methods.
Does not run benchmark tasks or execute supplied Python source.
"""

import asyncio
import json
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import harness.artifact_checks as checks
from harness.bounded_agent import BoundedTerminus2
from harness.recovery_agent import RecoveryTerminus2


def make_agent():
    """Bypass initialization so no model client is constructed."""
    agent = object.__new__(BoundedTerminus2)

    agent._idle_response_count = 0
    agent._recovery_reminders_sent = 0
    agent._action_after_reminder = False
    agent._completion_after_reminder = False
    agent._stopped_by_idle_guard = False

    agent._diagnostic_reminder_sent = False

    agent._artifact_paths = [
        "/app/artifacts/example.json"
    ]
    agent._artifact_manifest_paths = []
    agent._artifact_snapshot = {
        "status": "unavailable"
    }
    agent._artifact_reports = []
    agent._artifact_completion_requested = False
    agent._artifact_feedback = ""

    return agent


def model_response(commands=None, complete=False):
    """Match Terminus-2's six-item return value."""
    return (
        commands if commands is not None else [],
        complete,
        "",
        "Example analysis",
        "Example plan",
        object(),
    )


def artifact_report(valid):
    return {
        "status": "checked",
        "all_valid": valid,
        "checks": [
            {
                "path": "/app/artifacts/example.json",
                "valid": valid,
                "reason": (
                    "Valid JSON."
                    if valid
                    else "Output file is missing."
                ),
            }
        ],
        "truncated": False,
    }


async def interact(agent, prompt):
    return await agent._handle_llm_interaction(
        chat=None,
        prompt=prompt,
        logging_paths=(None, None, None),
    )


async def request_completion(agent, commands=None):
    parent = AsyncMock(
        return_value=model_response(
            commands=commands,
            complete=True,
        )
    )

    with patch.object(
        RecoveryTerminus2,
        "_handle_llm_interaction",
        parent,
    ):
        return await interact(
            agent,
            "Current observation",
        )


def check_dynamic_outputs():
    """Test real validators against temporary synthetic fixtures."""

    def prepare(
        instruction,
        paths=None,
        setup=None,
        manifests=None,
    ):
        with patch.object(
            checks,
            "_public_setup",
            return_value=setup or {},
        ):
            snapshot = checks.prepare_checks(
                instruction,
                paths or [],
                manifests or [],
            )

        # Exercise the JSON boundary used by the container bridge.
        return json.loads(
            json.dumps(snapshot)
        )

    def validate(snapshot):
        return checks.validate_outputs(
            snapshot["required_paths"],
            [],
            snapshot,
        )

    with TemporaryDirectory() as temporary:
        root = Path(temporary)

        # EPUB: one accepted filename is sufficient.
        novel = root / "novel"
        novel.mkdir()

        snapshot = prepare(
            f"TXT chapters are in `{novel}/`. "
            "Convert to EPUB and save in the same directory.\n"
            "Accepted output filenames are `Novel.epub`, "
            "`novel.epub`, or `novel_title.epub`."
        )

        assert not snapshot["errors"]
        assert len(snapshot["alternatives"]) == 1
        assert validate(snapshot)["all_valid"] is False

        with zipfile.ZipFile(
            novel / "novel.epub",
            "w",
        ) as archive:
            archive.writestr(
                "META-INF/container.xml",
                "<container/>",
            )

        assert validate(snapshot)["all_valid"] is True

        (novel / "novel.epub").write_text(
            "Not an EPUB",
            encoding="utf-8",
        )

        assert validate(snapshot)["all_valid"] is False

        print(
            "[OK] EPUB alternatives: missing/invalid fail; "
            "one permitted package passes."
        )

        # Python: discover files and check syntax without execution.
        source_dir = root / "source"
        source_dir.mkdir()

        sources = []

        for name in [
            "main.py",
            "block.py",
            "settings.py",
            "game.py",
        ]:
            path = source_dir / name
            path.write_text(
                "x = 1\n",
                encoding="utf-8",
            )
            sources.append(path)

        snapshot = prepare(
            "Given {path}, fix a bug in my Python code.",
            setup={
                "downloads": [
                    {"path": str(path)}
                    for path in sources
                ],
            },
        )

        assert not snapshot["errors"]
        assert len(snapshot["code_files"]) == 4
        assert validate(snapshot)["all_valid"] is True

        sources[0].write_text(
            "return 1\n",
            encoding="utf-8",
        )

        report = validate(snapshot)

        assert report["all_valid"] is False
        assert any(
            item["kind"] == "python_syntax"
            and item["changed"] is True
            and item["valid"] is False
            for item in report["checks"]
        )

        print(
            "[OK] Python discovery and syntax checks work "
            "without executing source."
        )

        # These synthetic bytes test rename integrity, not image decoding.
        pictures = root / "Pictures"
        pictures.mkdir()

        originals = []

        for index in range(3):
            path = pictures / f"picture{index}.jpg"
            path.write_bytes(
                f"synthetic image contents {index}".encode()
            )
            originals.append(path)

        snapshot = prepare(
            "Identify the pictures and change their filenames "
            "to the names of the mountains.",
            setup={
                "downloads": [
                    {"path": str(path)}
                    for path in originals
                ],
            },
        )

        assert not snapshot["errors"]
        assert len(snapshot["rename_groups"]) == 1
        assert validate(snapshot)["all_valid"] is False

        for index, path in enumerate(originals):
            path.rename(
                pictures / f"New name {index}.jpg"
            )

        assert validate(snapshot)["all_valid"] is True

        (pictures / "New name 0.jpg").write_bytes(
            b"Changed contents"
        )

        assert validate(snapshot)["all_valid"] is False

        print(
            "[OK] Renaming: old names fail; preserved-byte "
            "renames pass; changed bytes fail."
        )

        # Synthetic PDF envelopes test only the supported basic checks.
        blog = root / "Blog"

        snapshot = prepare(
            "Download the blogs opening now in PDF format "
            "and save them.",
            paths=[str(blog)],
            setup={
                "startup": {
                    "chrome_urls": [
                        "https://example.test/one",
                        "https://example.test/two",
                    ],
                },
            },
        )

        assert not snapshot["errors"]
        assert (
            snapshot["pdf_groups"][0]["expected_count"]
            == 2
        )

        blog.mkdir()

        pdf_fixture = (
            b"%PDF-1.4\n"
            b"Synthetic envelope fixture, not a full PDF.\n"
            b"%%EOF\n"
        )

        (blog / "one.pdf").write_bytes(
            pdf_fixture
        )
        assert validate(snapshot)["all_valid"] is False

        (blog / "two.pdf").write_bytes(
            pdf_fixture
        )
        assert validate(snapshot)["all_valid"] is True

        (blog / "two.pdf").write_text(
            "Not a PDF",
            encoding="utf-8",
        )
        assert validate(snapshot)["all_valid"] is False

        print(
            "[OK] PDF output count and basic header/end checks work."
        )

        # Public JSON must identify missing children inside existing dirs.
        artifacts = root / "artifacts"
        simulation = artifacts / "simulation"
        simulation.mkdir(parents=True)

        plan = root / "plan.json"
        plan.write_text(
            json.dumps({
                "simulation_output_dir": str(simulation),
                "required_simulation_artifacts": [
                    "required.mtr",
                    "run.err",
                ],
            }),
            encoding="utf-8",
        )

        snapshot = prepare(
            f"Given `{plan}`, write outputs under `{artifacts}`.",
            paths=[str(artifacts)],
            manifests=[str(plan)],
        )

        assert not snapshot["declaration_errors"]
        assert validate(snapshot)["all_valid"] is False

        for name in [
            "required.mtr",
            "run.err",
        ]:
            (simulation / name).write_text(
                "data",
                encoding="utf-8",
            )

        assert validate(snapshot)["all_valid"] is True

        print(
            "[OK] Public JSON declarations catch missing children "
            "inside existing directories."
        )

        # Missing preparation must not silently establish a pass.
        unknown = checks.validate_outputs(
            [str(simulation / "run.err")],
            [],
            None,
        )

        assert unknown["all_valid"] is None
        assert unknown["validation_errors"]

        # Truncated inspection must remain incomplete.
        limited = checks.validate_outputs(
            snapshot["required_paths"],
            [],
            snapshot,
            limit=1,
        )

        assert limited["all_valid"] is None
        assert limited["truncated"]

        print(
            "[OK] Missing snapshots and truncated coverage "
            "do not establish a pass."
        )

    print(
        "[NOTE] Fixtures do not verify functional repair, "
        "mountain names, article identity, or full PDF integrity."
    )


async def check_snapshot_order():
    """Verify baseline capture happens before parent task execution."""
    with TemporaryDirectory() as temporary:
        root = Path(temporary)

        pictures = root / "Pictures"
        pictures.mkdir()

        original = pictures / "picture.jpg"
        original.write_bytes(
            b"Synthetic image bytes"
        )

        renamed = pictures / "New name.jpg"

        setup = {
            "downloads": [
                {"path": str(original)}
            ],
        }

        events = []
        agent = make_agent()
        context = SimpleNamespace(
            metadata={"existing": "preserved"}
        )

        async def checker(action, payload):
            events.append(action)

            if action == "prepare":
                with patch.object(
                    checks,
                    "_public_setup",
                    return_value=setup,
                ):
                    return checks.prepare_checks(
                        **payload
                    )

            return checks.validate_outputs(
                **payload
            )

        async def parent_run(
            self,
            instruction,
            environment,
            context,
        ):
            events.append("parent_execution")
            assert original.exists()
            original.rename(renamed)

        with patch.object(
            agent,
            "_run_checker",
            new=AsyncMock(side_effect=checker),
        ):
            with patch.object(
                RecoveryTerminus2,
                "run",
                new=parent_run,
            ):
                await agent.run(
                    instruction=(
                        "Identify the pictures and change their "
                        "filenames to mountain names."
                    ),
                    environment=object(),
                    context=context,
                )

            assert events == [
                "prepare",
                "parent_execution",
            ]

            report = await agent._inspect_task_artifacts()

        assert events == [
            "prepare",
            "parent_execution",
            "validate",
        ]
        assert report["all_valid"] is True

        initial = context.metadata[
            "artifact_validation"
        ]["initial_snapshot"]

        assert (
            "picture.jpg"
            in initial["rename_groups"][0]["before"]
        )
        assert context.metadata["existing"] == "preserved"

        print(
            "[OK] Initial snapshot precedes parent execution "
            "and survives file renaming."
        )


async def check_artifact_integration():
    paths = BoundedTerminus2._extract_output_paths(
        "Input: `/app/input/source.csv`\n"
        "Output: `/app/artifacts/example.json`\n"
        "Repeated: `/app/artifacts/example.json`\n"
        "Other output: `/app/artifacts/my chart.png`\n"
        "Save the updated workbook in place at `/app/sales.xlsx`.\n"
        "Final output path: `/home/user/Desktop/image.docx`.\n"
        "Unsafe path: `/app/artifacts/../input/source.csv`"
    )

    assert paths == [
        "/app/artifacts/example.json",
        "/app/artifacts/my chart.png",
        "/app/sales.xlsx",
        "/home/user/Desktop/image.docx",
    ]

    print(
        "[OK] Explicit and save-in-place output paths selected."
    )

    agent = make_agent()
    events = []
    command = object()

    async def execute(commands, session):
        assert commands == [command]
        events.append("commands")
        return False, "Final terminal output"

    async def inspect():
        events.append("validation")
        return artifact_report(False)

    with patch.object(
        agent,
        "_inspect_task_artifacts",
        new=AsyncMock(side_effect=inspect),
    ) as checker:
        returned = await request_completion(
            agent,
            commands=[command],
        )

        assert returned[1] is True
        checker.assert_not_awaited()

        with patch.object(
            RecoveryTerminus2,
            "_execute_commands",
            new=AsyncMock(side_effect=execute),
        ):
            result = await agent._execute_commands(
                [command],
                session=None,
            )

        assert events == [
            "commands",
            "validation",
        ]
        assert result == (
            False,
            "Final terminal output",
        )
        assert len(agent._artifact_reports) == 1

    print(
        "[OK] Final commands execute before artifact validation."
    )

    with patch.object(
        RecoveryTerminus2,
        "_get_completion_confirmation_message",
        return_value="Original completion confirmation",
    ):
        message = agent._get_completion_confirmation_message(
            "Final terminal output"
        )

    assert message.startswith(
        "Original completion confirmation"
    )
    assert "/app/artifacts/example.json" in message
    assert "Output file is missing." in message
    assert "correct these problems" in message
    assert "inspect the actual final state" in message
    assert "a plausible URL alone is insufficient" in message

    print(
        "[OK] Confirmation preserves the original message and feedback."
    )
    print(
        "[OK] Completion-time evidence guidance is included."
    )

    with patch.object(
        agent,
        "_inspect_task_artifacts",
        new=AsyncMock(
            return_value=artifact_report(True)
        ),
    ) as checker:
        await request_completion(agent)

        with patch.object(
            RecoveryTerminus2,
            "_execute_commands",
            new=AsyncMock(
                return_value=(False, "Updated output")
            ),
        ):
            await agent._execute_commands(
                [],
                session=None,
            )

        checker.assert_awaited_once()

    assert len(agent._artifact_reports) == 2
    assert (
        agent._artifact_reports[-1]["all_valid"]
        is True
    )
    assert agent._artifact_feedback == ""

    print(
        "[OK] A later completion request rechecks corrected output."
    )
    print(
        "[OK] Passing file checks do not produce positive feedback."
    )

    with patch.object(
        agent,
        "_inspect_task_artifacts",
        new=AsyncMock(),
    ) as checker:
        await request_completion(agent)

        with patch.object(
            RecoveryTerminus2,
            "_execute_commands",
            new=AsyncMock(
                return_value=(False, "Output")
            ),
        ):
            await agent._execute_commands(
                [],
                session=None,
            )

        checker.assert_not_awaited()

    assert len(agent._artifact_reports) == 2

    print(
        "[OK] Artifact checks are limited to two per task."
    )

    agent = make_agent()

    with patch.object(
        agent,
        "_inspect_task_artifacts",
        new=AsyncMock(),
    ) as checker:
        with patch.object(
            RecoveryTerminus2,
            "_execute_commands",
            new=AsyncMock(
                return_value=(False, "Normal output")
            ),
        ):
            await agent._execute_commands(
                [],
                session=None,
            )

        checker.assert_not_awaited()

    print(
        "[OK] Ordinary command steps do not trigger checks."
    )

    agent = make_agent()
    agent._artifact_completion_requested = True

    with patch.object(
        agent,
        "_inspect_task_artifacts",
        new=AsyncMock(),
    ) as checker:
        with patch.object(
            RecoveryTerminus2,
            "_execute_commands",
            new=AsyncMock(
                return_value=(True, "Command timed out")
            ),
        ):
            result = await agent._execute_commands(
                [],
                session=None,
            )

        checker.assert_not_awaited()

    assert result == (
        True,
        "Command timed out",
    )
    assert agent._artifact_reports == []

    print(
        "[OK] Timed-out commands are not treated as finished outputs."
    )

    agent = make_agent()
    agent._artifact_completion_requested = True

    with patch.object(
        agent,
        "_inspect_task_artifacts",
        new=AsyncMock(
            side_effect=RuntimeError("Test failure")
        ),
    ):
        with patch.object(
            RecoveryTerminus2,
            "_execute_commands",
            new=AsyncMock(
                return_value=(False, "Output")
            ),
        ):
            result = await agent._execute_commands(
                [],
                session=None,
            )

    report = agent._artifact_reports[0]

    assert report["status"] == "checker_error"
    assert report["all_valid"] is None
    assert report["seconds"] >= 0
    assert result == (False, "Output")
    assert (
        "no validity conclusion"
        in agent._artifact_feedback
    )

    print(
        "[OK] Checker errors remain unknown and do not crash execution."
    )

    skipped_feedback = agent._format_artifact_feedback({
        "status": "not_checked",
        "all_valid": None,
        "checks": [],
        "reason": "No selected output paths.",
    })

    assert skipped_feedback == ""

    print(
        "[OK] Skipped checks do not produce success feedback."
    )


async def check_diagnostic_reminder():
    examples = [
        (
            "fatal error",
            "EnergyPlus Terminated with a Fatal Error. "
            "Check eplusout.err log.",
        ),
        (
            "Python traceback",
            "Traceback (most recent call last):\n"
            "  File \"example.py\", line 4\n"
            "ValueError: example failure",
        ),
    ]

    for label, original_prompt in examples:
        agent = make_agent()

        parent = AsyncMock(
            return_value=model_response(
                commands=[object()],
            )
        )

        with patch.object(
            RecoveryTerminus2,
            "_handle_llm_interaction",
            parent,
        ):
            await interact(agent, original_prompt)
            await interact(agent, original_prompt)

        assert parent.await_count == 2

        first_prompt = (
            parent.await_args_list[0].kwargs["prompt"]
        )
        second_prompt = (
            parent.await_args_list[1].kwargs["prompt"]
        )

        assert first_prompt.startswith(
            original_prompt
        )
        assert (
            first_prompt.count(
                "Harness diagnostic notice:"
            ) == 1
        )
        assert (
            "inspect the diagnostic log"
            in first_prompt
        )

        assert second_prompt == original_prompt
        assert agent._diagnostic_reminder_sent is True

        print(
            f"[OK] {label} triggers the diagnostic reminder once."
        )

    agent = make_agent()
    ordinary_prompt = "Command completed successfully."

    parent = AsyncMock(
        return_value=model_response(
            commands=[object()]
        )
    )

    with patch.object(
        RecoveryTerminus2,
        "_handle_llm_interaction",
        parent,
    ):
        await interact(
            agent,
            ordinary_prompt,
        )

    assert (
        parent.await_args.kwargs["prompt"]
        == ordinary_prompt
    )
    assert agent._diagnostic_reminder_sent is False

    print(
        "[OK] Normal observations do not trigger diagnostic guidance."
    )


async def check_task_reset_and_metadata():
    """Test run() state reset with preparation and parent calls mocked."""
    agent = make_agent()

    context = SimpleNamespace(
        metadata={
            "existing_metadata": "preserved"
        }
    )

    fatal_prompt = (
        "Execution failed with a Fatal Error. "
        "Check the diagnostic log."
    )

    parent_interaction = AsyncMock(
        return_value=model_response(
            commands=[object()]
        )
    )

    async def parent_run(
        self,
        instruction,
        environment,
        context,
    ):
        for prompt in environment:
            await interact(
                self,
                prompt,
            )

    prepared_snapshot = {
        "status": "prepared",
        "has_checks": False,
        "errors": [],
        "declaration_errors": [],
    }

    with patch.object(
        agent,
        "_run_checker",
        new=AsyncMock(
            return_value=prepared_snapshot
        ),
    ), patch.object(
        RecoveryTerminus2,
        "run",
        new=parent_run,
    ):
        with patch.object(
            RecoveryTerminus2,
            "_handle_llm_interaction",
            parent_interaction,
        ):
            await agent.run(
                instruction="Original task instruction",
                environment=[fatal_prompt],
                context=context,
            )

            assert (
                context.metadata["diagnostic_recovery"]
                == {"reminder_sent": True}
            )
            assert (
                context.metadata["existing_metadata"]
                == "preserved"
            )

            parent_interaction.reset_mock()

            await agent.run(
                instruction="Another original instruction",
                environment=["Normal terminal output"],
                context=context,
            )

            assert (
                context.metadata["diagnostic_recovery"]
                == {"reminder_sent": False}
            )
            assert (
                agent._diagnostic_reminder_sent
                is False
            )
            assert (
                parent_interaction.await_args.kwargs["prompt"]
                == "Normal terminal output"
            )

            parent_interaction.reset_mock()

            await agent.run(
                instruction="Third original instruction",
                environment=[fatal_prompt],
                context=context,
            )

            assert (
                context.metadata["diagnostic_recovery"]
                == {"reminder_sent": True}
            )
            assert (
                "Harness diagnostic notice:"
                in parent_interaction.await_args.kwargs["prompt"]
            )

    print(
        "[OK] Diagnostic state resets between task attempts."
    )
    print(
        "[OK] Diagnostic metadata is recorded."
    )
    print(
        "[OK] Existing context metadata is preserved."
    )


async def main():
    check_dynamic_outputs()
    await check_snapshot_order()
    await check_artifact_integration()
    await check_diagnostic_reminder()
    await check_task_reset_and_metadata()

    print(
        "\nAll offline harness checks passed."
    )
    print(
        "No model clients, API calls, or benchmark attempts were used."
    )
    print(
        "Transport is mocked. These tests do not establish task "
        "accuracy, spending limits, or full Harbor/Docker compatibility."
    )


if __name__ == "__main__":
    asyncio.run(main())