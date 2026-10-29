"""Bounded guidance and pre/post output checks.

The official verifier remains unchanged.

The updated RecoveryTerminus2 must pass the starting instruction
unchanged, as in the version already provided.
"""

import json
import re
import shlex
from pathlib import Path, PurePosixPath
from time import monotonic

from .recovery_agent import RecoveryTerminus2


RECOVERY_REMINDER = """
Harness notice: your last two responses contained no executable
commands and did not request task completion.

Take one concrete diagnostic or corrective action based on the
observed terminal state. Do not repeat the same explanation.

If you cannot proceed, explicitly request task completion so the
current state can be graded. Do not claim the task succeeded.
""".strip()


class IdleResponseLimitReached(Exception):
    """Internal signal for a controlled harness stop."""


class BoundedTerminus2(RecoveryTerminus2):
    IDLE_RESPONSE_LIMIT = 3
    RECOVERY_REMINDER_AT = 2

    MAX_ARTIFACT_CHECKS = 2
    MAX_ARTIFACT_PATHS = 100
    ARTIFACT_CHECK_TIMEOUT_SEC = 30

    @staticmethod
    def _extract_output_paths(instruction):
        paths = []

        for match in re.finditer(
            r"`(/[^`\r\n]+)`",
            instruction,
        ):
            path = match.group(1)

            if (
                ".." in PurePosixPath(path).parts
                or any(
                    character in path
                    for character in "*?{}"
                )
            ):
                continue

            before = instruction[:match.start()]

            clause = re.split(
                r"\n|[.!?]\s+",
                before,
            )[-1]

            selected = bool(
                re.search(
                    r"\b(?:save|write|create|export|generate|store)\b"
                    r"|\bresult\s+as\b"
                    r"|\bkeep\s+(?:the\s+)?solver\s+log\b",
                    clause,
                    re.IGNORECASE,
                )
                or re.search(
                    r"\boutputs?(?:\s+paths?)?\s*:",
                    clause,
                    re.IGNORECASE,
                )
            )

            if not selected and re.fullmatch(
                r"\s*(?:[-*]|\d+[.)])?\s*",
                clause,
            ):
                for line in reversed(
                    before.splitlines()[:-1]
                ):
                    if (
                        not line.strip()
                        or re.match(
                            r"^\s*(?:[-*]|\d+[.)])\s",
                            line,
                        )
                    ):
                        continue

                    selected = bool(
                        re.fullmatch(
                            r"(?:required\s+)?"
                            r"(?:final\s+)?"
                            r"outputs?\s*:",
                            line.strip(),
                            re.IGNORECASE,
                        )
                    )
                    break

            if selected and path not in paths:
                paths.append(path)

        return paths

    async def run(self, instruction, environment, context):
        self._idle_response_count = 0
        self._recovery_reminders_sent = 0
        self._action_after_reminder = False
        self._completion_after_reminder = False
        self._stopped_by_idle_guard = False
        self._diagnostic_reminder_sent = False

        self._artifact_environment = environment
        self._artifact_paths = self._extract_output_paths(
            instruction
        )

        self._artifact_manifest_paths = []

        roots = [
            PurePosixPath(path)
            for path in self._artifact_paths
        ]

        for match in re.finditer(
            r"`(/[^`\r\n]+)`",
            instruction,
        ):
            candidate = PurePosixPath(
                match.group(1)
            )

            if (
                candidate.suffix.lower() != ".json"
                or ".." in candidate.parts
                or any(
                    character in str(candidate)
                    for character in "*?{}"
                )
            ):
                continue

            if any(
                candidate == root
                or root in candidate.parents
                for root in roots
            ):
                continue

            text = str(candidate)

            if text not in self._artifact_manifest_paths:
                self._artifact_manifest_paths.append(text)

        self._artifact_reports = []
        self._artifact_completion_requested = False
        self._artifact_feedback = ""

        self._artifact_snapshot = {
            "status": "unavailable"
        }
        self._artifact_preparation_seconds = 0.0

        try:
            # Capture original state before the model starts.
            started = monotonic()

            try:
                self._artifact_snapshot = (
                    await self._run_checker(
                        "prepare",
                        {
                            "instruction": instruction,
                            "paths": self._artifact_paths,
                            "manifest_paths": (
                                self._artifact_manifest_paths
                            ),
                        },
                    )
                )

                if (
                    self._artifact_snapshot.get("status")
                    != "prepared"
                ):
                    raise ValueError(
                        "Unexpected preparation result."
                    )

            except Exception as error:
                # Preparation problems are recorded, not treated as
                # successful validation or used to block the agent.
                self._artifact_snapshot = {
                    "status": "unavailable",
                    "errors": [
                        {
                            "stage": "preparation",
                            "reason": (
                                f"{type(error).__name__}: {error}"
                            ),
                        }
                    ],
                }

            finally:
                self._artifact_preparation_seconds = round(
                    monotonic() - started,
                    6,
                )

            await super().run(
                instruction=instruction,
                environment=environment,
                context=context,
            )

        except IdleResponseLimitReached:
            self._stopped_by_idle_guard = True

            self.logger.warning(
                "Harness stopped after %s consecutive idle responses.",
                self.IDLE_RESPONSE_LIMIT,
            )

        finally:
            metadata = dict(
                context.metadata or {}
            )

            metadata["idle_response_guard"] = {
                "enabled": True,
                "limit": self.IDLE_RESPONSE_LIMIT,
                "reminder_at": self.RECOVERY_REMINDER_AT,
                "reminders_sent": (
                    self._recovery_reminders_sent
                ),
                "consecutive_idle_responses": (
                    self._idle_response_count
                ),
                "action_after_reminder": (
                    self._action_after_reminder
                ),
                "completion_after_reminder": (
                    self._completion_after_reminder
                ),
                "triggered": self._stopped_by_idle_guard,
            }

            metadata["diagnostic_recovery"] = {
                "reminder_sent": (
                    self._diagnostic_reminder_sent
                ),
            }

            metadata["artifact_validation"] = {
                "enabled": True,
                "scope": (
                    "Explicit outputs, public JSON declarations, "
                    "accepted alternatives, discovered Python syntax, "
                    "rename integrity, and basic browser-PDF checks"
                ),
                "selector": "instruction_text_heuristic_v2",
                "required_paths": self._artifact_paths,
                "manifest_paths": self._artifact_manifest_paths,
                "initial_snapshot": self._artifact_snapshot,
                "preparation_seconds": (
                    self._artifact_preparation_seconds
                ),
                "max_checks": self.MAX_ARTIFACT_CHECKS,
                "check_attempts": len(
                    self._artifact_reports
                ),
                "checks_performed": sum(
                    report.get("status") == "checked"
                    for report in self._artifact_reports
                ),
                "checks_skipped": sum(
                    report.get("status") == "not_checked"
                    for report in self._artifact_reports
                ),
                "checker_errors": sum(
                    report.get("status") == "checker_error"
                    for report in self._artifact_reports
                ),
                "reports": self._artifact_reports,
                "validation_seconds": sum(
                    report.get("seconds", 0.0)
                    for report in self._artifact_reports
                ),
                "limitation": (
                    "Checks do not prove semantic correctness, "
                    "functional repair, correct mountain names, "
                    "article correspondence, or browser/system-state "
                    "correctness. No total spending cap is added."
                ),
            }

            context.metadata = metadata

    async def _handle_llm_interaction(
        self,
        chat,
        prompt,
        logging_paths,
        original_instruction="",
        session=None,
    ):
        if (
            self._idle_response_count
            >= self.IDLE_RESPONSE_LIMIT
        ):
            raise IdleResponseLimitReached(
                "Three consecutive responses produced no commands "
                "and no task-completion request."
            )

        if (
            self._idle_response_count
            == self.RECOVERY_REMINDER_AT
            and getattr(
                self,
                "_recovery_reminders_sent",
                0,
            ) == 0
        ):
            prompt = (
                f"{prompt}\n\n{RECOVERY_REMINDER}"
            )
            self._recovery_reminders_sent = 1

        diagnostic_failure = re.search(
            r"\bfatal\s+error\b"
            r"|Traceback \(most recent call last\):",
            prompt,
            re.IGNORECASE,
        )

        if (
            diagnostic_failure
            and not getattr(
                self,
                "_diagnostic_reminder_sent",
                False,
            )
        ):
            prompt += (
                "\n\nHarness diagnostic notice: the latest output "
                "reports an execution failure. Before rewriting the "
                "solution or retrying, inspect the diagnostic log "
                "named by the tool, or the traceback's failing "
                "operation. If its location is unknown, locate it "
                "in the working or output directories. Do not assume "
                "the log is inaccessible because execution failed. "
                "Base corrections on observed diagnostics. "
                "Do not substitute invented results or "
                "placeholder artifacts."
            )

            self._diagnostic_reminder_sent = True

        result = await super()._handle_llm_interaction(
            chat=chat,
            prompt=prompt,
            logging_paths=logging_paths,
            original_instruction=original_instruction,
            session=session,
        )

        (
            commands,
            complete,
            feedback,
            analysis,
            plan,
            response,
        ) = result

        self._artifact_completion_requested = bool(
            complete
        )
        self._artifact_feedback = ""

        if getattr(
            self,
            "_recovery_reminders_sent",
            0,
        ):
            if commands:
                self._action_after_reminder = True

            if complete:
                self._completion_after_reminder = True

        if commands or complete or feedback:
            self._idle_response_count = 0
        else:
            self._idle_response_count += 1

        return result

    async def _execute_commands(self, commands, session):
        timeout, output = (
            await super()._execute_commands(
                commands,
                session,
            )
        )

        reports = getattr(
            self,
            "_artifact_reports",
            None,
        )

        if (
            not getattr(
                self,
                "_artifact_completion_requested",
                False,
            )
            or reports is None
            or len(reports) >= self.MAX_ARTIFACT_CHECKS
            or timeout
        ):
            return timeout, output

        started = monotonic()

        try:
            report = await self._inspect_task_artifacts()

        except Exception as error:
            report = {
                "status": "checker_error",
                "all_valid": None,
                "checks": [],
                "reason": (
                    "Artifact checker failed: "
                    f"{type(error).__name__}: {error}"
                ),
            }

        report["seconds"] = round(
            monotonic() - started,
            6,
        )

        reports.append(report)

        self._artifact_feedback = (
            self._format_artifact_feedback(report)
        )

        return timeout, output

    def _get_completion_confirmation_message(
        self,
        terminal_output,
    ):
        message = (
            super()._get_completion_confirmation_message(
                terminal_output
            )
        )

        message += (
            "\n\nBefore confirming completion, inspect the actual "
            "final state against the original request. Executing a "
            "command does not establish that it worked. For browser "
            "tasks, inspect the active URL and relevant page content; "
            "a plausible URL alone is insufficient. For file tasks, "
            "inspect saved contents, not just existence. "
            "If verification fails, use available tools to "
            "diagnose and correct it."
        )

        feedback = getattr(
            self,
            "_artifact_feedback",
            "",
        )

        if feedback:
            return f"{message}\n\n{feedback}"

        return message

    async def _run_checker(self, action, payload):
        """Upload, execute, and remove one temporary checker copy."""
        helper = Path(__file__).with_name(
            "artifact_checks.py"
        )

        if not helper.is_file():
            raise FileNotFoundError(
                "artifact_checks.py is missing."
            )

        environment = self._artifact_environment

        created = await environment.exec(
            command="mktemp -d /tmp/pe6203-checks-XXXXXXXX",
            timeout_sec=10,
        )

        directory = created.stdout.strip()

        if (
            created.return_code != 0
            or not re.fullmatch(
                r"/tmp/pe6203-checks-[A-Za-z0-9]+",
                directory,
            )
        ):
            raise RuntimeError(
                "Could not create checker directory."
            )

        remote_helper = (
            f"{directory}/artifact_checks.py"
        )

        program = (
            "import json,runpy,sys; "
            "m=runpy.run_path(sys.argv[1]); "
            "action=sys.argv[2]; "
            "payload=json.loads(sys.argv[3]); "
            "name={'prepare':'prepare_checks',"
            "'validate':'validate_outputs'}[action]; "
            "print(json.dumps(m[name](**payload)))"
        )

        try:
            await environment.upload_file(
                source_path=helper,
                target_path=remote_helper,
            )

            result = await environment.exec(
                command=shlex.join([
                    "python3",
                    "-c",
                    program,
                    remote_helper,
                    action,
                    json.dumps(payload),
                ]),
                timeout_sec=(
                    self.ARTIFACT_CHECK_TIMEOUT_SEC
                ),
            )

            if result.return_code != 0:
                raise RuntimeError(
                    "Checker process exited with code "
                    f"{result.return_code}."
                )

            report = json.loads(
                result.stdout
            )

            if not isinstance(report, dict):
                raise ValueError(
                    "Checker returned an invalid report."
                )

            return report

        finally:
            try:
                await environment.exec(
                    command=shlex.join([
                        "rm",
                        "-rf",
                        "--",
                        directory,
                    ]),
                    timeout_sec=10,
                )

            except Exception:
                pass

    async def _inspect_task_artifacts(self):
        snapshot = getattr(
            self,
            "_artifact_snapshot",
            None,
        )

        if (
            isinstance(snapshot, dict)
            and snapshot.get("status") == "prepared"
        ):
            if (
                not snapshot.get("has_checks")
                and not snapshot.get("errors")
                and not snapshot.get("declaration_errors")
            ):
                return {
                    "status": "not_checked",
                    "all_valid": None,
                    "checks": [],
                    "reason": (
                        "No supported file-output requirements "
                        "identified; browser/system state "
                        "is not file-validated."
                    ),
                }

        report = await self._run_checker(
            "validate",
            {
                "paths": self._artifact_paths,
                "manifest_paths": getattr(
                    self,
                    "_artifact_manifest_paths",
                    [],
                ),
                "snapshot": snapshot,
                "limit": self.MAX_ARTIFACT_PATHS,
            },
        )

        if (
            report.get("status") != "checked"
            or not isinstance(
                report.get("checks"),
                list,
            )
        ):
            raise ValueError(
                "Invalid artifact validation report."
            )

        return report

    @staticmethod
    def _format_artifact_feedback(report):
        if report.get("status") == "not_checked":
            return ""

        if report.get("status") != "checked":
            return (
                "Harness artifact check: no validity conclusion. "
                f"{report.get('reason', '')}"
            )

        failures = [
            check
            for check in report["checks"]
            if check.get("valid") is False
        ]

        errors = (
            list(
                report.get("declaration_errors") or []
            )
            + list(
                report.get("validation_errors") or []
            )
        )

        pieces = []

        if failures:
            details = "\n".join(
                f"- {check['path']}: "
                f"{str(check.get('reason', 'Invalid output'))[:400]}"
                for check in failures[:10]
            )

            pieces.append(
                "Harness artifact check found output-file problems:\n"
                + details
                + "\nUse the normal next response to correct these "
                "problems before confirming completion. "
                "Do not create placeholders. "
                "These checks do not establish task correctness."
            )

        if errors:
            details = "\n".join(
                f"- {str(error.get('reason', 'Unknown issue'))[:300]}"
                for error in errors[:3]
            )

            pieces.append(
                "Harness validation is incomplete; some requirements "
                "could not be resolved:\n"
                + details
                + "\nInspect the supplied requirements directly. "
                "Do not treat this as confirmation of success."
            )

        if report.get("truncated"):
            pieces.append(
                "Harness validation reached its inspection limit; "
                "coverage is incomplete."
            )

        return "\n\n".join(pieces)