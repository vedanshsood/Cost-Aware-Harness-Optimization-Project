"""Run the bounded evidence/diagnostic variant.

Default:
- All 40 evaluation tasks.
- One attempt per task.
- Sequential execution.
- No automatic trial retries.

Coverage warnings do not prevent execution.
The official verifier determines task rewards.

Requires scripts/run_tasks.py for shared helpers.
No Dockerfile changes are required.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

import run_tasks as common


ROOT = Path(__file__).resolve().parents[1]

AGENT = "harness.bounded_agent:BoundedTerminus2"
VARIANT = "bounded-evidence-diagnostic"


def harness_hashes():
    """Record the exact harness source used for this batch."""
    paths = [
        ROOT / "harness" / "__init__.py",
        ROOT / "harness" / "recovery_agent.py",
        ROOT / "harness" / "bounded_agent.py",
        ROOT / "harness" / "artifact_checks.py",
    ]

    hashes = {}

    for path in paths:
        if not path.is_file():
            raise RuntimeError(
                f"Missing harness file: {path}"
            )

        hashes[path.relative_to(ROOT).as_posix()] = (
            hashlib.sha256(path.read_bytes()).hexdigest()
        )

    return hashes


def selected_tasks(selection, phase):
    """Validate the shared selection without changing it."""
    validated = {}

    for name, expected in {
        "development": 5,
        "evaluation": 40,
    }.items():
        tasks = selection.get(name)

        if (
            not isinstance(tasks, list)
            or len(tasks) != expected
            or not all(
                isinstance(task, str)
                and re.fullmatch(
                    r"[A-Za-z0-9_-]+",
                    task,
                )
                for task in tasks
            )
            or len(set(tasks)) != expected
        ):
            raise ValueError(
                f"Expected {expected} unique valid "
                f"{name} task IDs."
            )

        validated[name] = tasks

    if (
        set(validated["development"])
        & set(validated["evaluation"])
    ):
        raise ValueError(
            "Development and evaluation tasks overlap."
        )

    return validated[phase]


class Runtime:
    """Construct commands for the existing Docker runtime."""

    def __init__(self, assets):
        self.image = assets["image"]
        self.platform = assets["platform"]
        self.volume = assets["asset_volume"]

        image_info = json.loads(
            common.capture([
                "docker",
                "image",
                "inspect",
                self.image,
            ])
        )[0]

        if image_info["Id"] != assets["image_id"]:
            raise RuntimeError(
                "Runtime image differs from asset_info.json. "
                "Resolve the mismatch before continuing."
            )

        volume_info = json.loads(
            common.capture([
                "docker",
                "volume",
                "inspect",
                self.volume,
            ])
        )[0]

        self.shared_root = volume_info["Mountpoint"]

        if not self.shared_root.startswith("/"):
            raise RuntimeError(
                "Expected a Linux Docker volume mountpoint."
            )

    def command(self, *arguments, name=None, tmp=None):
        command = [
            "docker",
            "run",
            "--platform",
            self.platform,
        ]

        if name is None:
            command.append("--rm")

        else:
            command.extend([
                "--name",
                name,
                "--env",
                "OPENROUTER_API_KEY",
                "--env",
                f"TMPDIR={tmp}",
                "--env",
                f"DOCKER_DEFAULT_PLATFORM={self.platform}",
            ])

        command.extend([
            "--mount",
            "type=bind,source=/var/run/docker.sock,"
            "target=/var/run/docker.sock",

            "--mount",
            f"type=volume,source={self.volume},"
            "target=/opt/tua-bench",

            "--mount",
            f"type=volume,source={self.volume},"
            f"target={self.shared_root}",

            "--mount",
            f"type=bind,source={ROOT / 'harness'},"
            "target=/project/harness,readonly",

            "--env",
            "PYTHONPATH=/project",

            "--env",
            "PYTHONDONTWRITEBYTECODE=1",

            "--workdir",
            self.shared_root,

            self.image,
            *arguments,
        ])

        return command

    def task_path(self, task):
        return str(
            PurePosixPath(self.shared_root)
            / "tasks"
            / task
        )


def check_output_coverage(runtime, tasks):
    """Report planned checks without blocking task execution.

    Actual preparation and validation results are recorded
    inside each task environment.
    """
    state_tasks = {
        "028-civil-division-forms",
        "034-turn-off-dark-mode",
        "041-baby-name-carl",
        "044-etsy-saved-passwords",
        "045-united-bag-fee-page",
        "046-restore-tripadvisor-tab",
        "051-hide-left-dock",
        "057-set-undo-steps-100",
        "089-install-recommended-exts",
        "094-author-homepage-bookmarks",
        "105-search-cell-b6",
        "106-create-charles-ssh-user",
    }

    basic_file_tasks = {
        "000-count-nuclei",
        "003-rebuild-energy-model",
        "010-pivot-product-revenue",
        "021-fill-ramp-chart",
        "022-monthly-sales-line-chart",
        "025-product-channel-pivots",
        "033-prostate-volume-est",
        "049-remove-dog-background",
        "053-make-palette-png",
        "054-prostate-label-obj",
        "059-make-summary-slide",
        "062-add-baseball-audio",
        "071-paste-image-docx",
        "074-apa-references-review",
        "084-plate-thermal-sim",
        "087-spreadsheet-to-doc-table",
        "090-ecs-grf-pass-rates",
        "099-professor-contact-info",
        "101-rearrange-warm-tiles",
        "102-daily-email-report",
        "116-bottom-left-page-numbers",
        "117-comma-text-to-table",
        "118-set-times-new-roman",
        "119-tabstop-sentence-split",
    }

    dynamic_file_tasks = {
        "080-convert-novel-epub": {
            "kind": "output_alternatives",
            "reason": (
                "Resolve accepted filenames and their directory "
                "from the instruction. Require at least one output "
                "to pass basic package checks."
            ),
        },
        "092-fix-tetris-bug": {
            "kind": "python_syntax",
            "reason": (
                "Discover Python sources from public setup metadata. "
                "Check syntax and record whether contents changed. "
                "Functional bug repair is not established."
            ),
        },
        "100-name-mountain-photos": {
            "kind": "image_rename_integrity",
            "reason": (
                "Capture original image names and hashes before "
                "execution. Check renamed files preserve image bytes. "
                "Mountain identification is not established."
            ),
        },
        "103-download-blog-pdfs": {
            "kind": "browser_pdf_outputs",
            "reason": (
                "Use setup-declared initial URLs and snapshot "
                "existing PDFs. Check new or modified output count "
                "and basic PDF header/end markers. "
                "Article identity is not established."
            ),
        },
    }

    dynamic_ids = set(dynamic_file_tasks)

    if (
        state_tasks & basic_file_tasks
        or state_tasks & dynamic_ids
        or basic_file_tasks & dynamic_ids
    ):
        raise RuntimeError(
            "Coverage audit categories overlap."
        )

    reviewed = (
        state_tasks
        | basic_file_tasks
        | dynamic_ids
    )

    audit_code = """
import json
import sys
from pathlib import Path

from harness.bounded_agent import BoundedTerminus2

shared_root, *task_ids = sys.argv[1:]
rows = []

for task_id in task_ids:
    instruction = (
        Path(shared_root)
        / "tasks"
        / task_id
        / "instruction.md"
    ).read_text(encoding="utf-8")

    rows.append({
        "task_id": task_id,
        "selected_outputs": (
            BoundedTerminus2._extract_output_paths(instruction)
        ),
    })

print(json.dumps(rows))
"""

    rows = json.loads(
        common.capture(
            runtime.command(
                "python",
                "-c",
                audit_code,
                runtime.shared_root,
                *tasks,
            )
        )
    )

    if (
        not isinstance(rows, list)
        or len(rows) != len(tasks)
        or any(
            not isinstance(row, dict)
            for row in rows
        )
        or [
            row.get("task_id")
            for row in rows
        ] != tasks
    ):
        raise RuntimeError(
            "Invalid output-coverage audit result."
        )

    report = []
    coverage_warnings = []

    print("\nPlanned output checks:")

    for row in rows:
        task = row["task_id"]
        paths = row.get("selected_outputs")
        planned_kinds = []

        if (
            not isinstance(paths, list)
            or not all(
                isinstance(path, str)
                for path in paths
            )
        ):
            raise RuntimeError(
                f"Invalid selected-output list for {task}."
            )

        if task not in reviewed:
            status = "unreviewed"
            reason = (
                "Task requirements have not been classified "
                "in this audit."
            )
            coverage_warnings.append(
                f"{task}: {reason}"
            )

        elif task in dynamic_file_tasks:
            status = "dynamic_checks_planned"

            planned_kinds = [
                dynamic_file_tasks[task]["kind"]
            ]

            reason = (
                dynamic_file_tasks[task]["reason"]
                + " Availability is confirmed only when the "
                "task-container preparation snapshot is created."
            )

        elif task in state_tasks:
            status = "file_check_inapplicable"
            reason = (
                "Requires browser, application, or system state. "
                "That state is not automatically file-validated."
            )

            if paths:
                coverage_warnings.append(
                    f"{task}: unexpected selected file targets; "
                    "review whether they are inputs."
                )

        elif not paths:
            status = "coverage_gap"
            reason = (
                "A reviewed file-producing task has no "
                "selected output paths."
            )
            coverage_warnings.append(
                f"{task}: {reason}"
            )

        else:
            status = "basic_file_checks_planned"
            planned_kinds = ["basic_file"]
            reason = (
                "Check explicit output paths. Supported required "
                "children from public input JSON are captured "
                "before model execution. Semantic correctness "
                "is not established."
            )

        report.append({
            "task_id": task,
            "status": status,
            "selected_outputs": paths,
            "planned_check_kinds": planned_kinds,
            "reason": reason,
        })

        print(f"\n[{status.upper()}] {task}")

        for path in paths:
            print(f"  Explicit target: {path}")

        for kind in planned_kinds:
            print(f"  Planned check: {kind}")

        print(f"  {reason}")

    if coverage_warnings:
        print("\n[WARN] Non-blocking audit warnings:")

        for warning in coverage_warnings:
            print(f"  - {warning}")

    print(
        "\n[INFO] This report describes planned checks, "
        "not successful runtime validation."
    )
    print(
        "[INFO] Actual preparation errors, snapshots, "
        "and validation results are stored in each task JSON."
    )
    print(
        "[INFO] Coverage warnings do not prevent task execution."
    )

    return report


def preflight(runtime, tasks, commit):
    """Verify runtime, benchmark, imports, and Docker path access."""
    validation_code = """
import json
import subprocess
import sys
import tomllib
from pathlib import Path

commit, shared_root, *task_ids = sys.argv[1:]
root = Path("/opt/tua-bench")

actual = subprocess.check_output(
    ["git", "rev-parse", "HEAD"],
    cwd=root,
    text=True,
).strip()

if actual != commit:
    raise RuntimeError("Prepared benchmark commit differs.")

marker = json.loads(
    (root / ".pe6203-assets-ready.json").read_text()
)

if marker.get("benchmark_commit") != commit:
    raise RuntimeError("Prepared asset marker differs.")

budgets = {}

for task_id in task_ids:
    task = Path(shared_root) / "tasks" / task_id

    for filename in ["instruction.md", "task.toml"]:
        if not (task / filename).is_file():
            raise RuntimeError(
                f"Missing file: {task_id}/{filename}"
            )

    config = tomllib.loads(
        (task / "task.toml").read_text()
    )

    budgets[task_id] = {
        "agent_timeout_sec": config.get(
            "agent", {}
        ).get("timeout_sec"),
        "verifier_timeout_sec": config.get(
            "verifier", {}
        ).get("timeout_sec"),
        "step_limit": None,
        "step_limit_note": (
            "Inherited Terminus-2 episode limit; "
            "not resolved by this preflight. "
            "The idle guard is an additional stopping rule, "
            "not a total spending limit."
        ),
    }

print(json.dumps(budgets))
"""

    budgets = json.loads(
        common.capture(
            runtime.command(
                "python",
                "-c",
                validation_code,
                commit,
                runtime.shared_root,
                *tasks,
            )
        )
    )

    print(
        f"[OK] Benchmark and {len(tasks)} "
        "task definitions verified."
    )

    import_code = """
from harness.bounded_agent import BoundedTerminus2
from harness.recovery_agent import RecoveryTerminus2
from harness.artifact_checks import (
    check_artifacts,
    expand_declared_outputs,
    prepare_checks,
    validate_outputs,
)

assert issubclass(BoundedTerminus2, RecoveryTerminus2)

assert BoundedTerminus2.IDLE_RESPONSE_LIMIT == 3
assert BoundedTerminus2.RECOVERY_REMINDER_AT == 2
assert BoundedTerminus2.MAX_ARTIFACT_CHECKS == 2
assert BoundedTerminus2.MAX_ARTIFACT_PATHS == 100
assert BoundedTerminus2.ARTIFACT_CHECK_TIMEOUT_SEC == 30

assert callable(check_artifacts)
assert callable(expand_declared_outputs)
assert callable(prepare_checks)
assert callable(validate_outputs)

paths = BoundedTerminus2._extract_output_paths(
    "Required output: `/app/artifacts/example.json`"
)
assert paths == ["/app/artifacts/example.json"]

paths = BoundedTerminus2._extract_output_paths(
    "Save the updated workbook in place at `/app/example.xlsx`."
)
assert paths == ["/app/example.xlsx"]

paths = BoundedTerminus2._extract_output_paths(
    "Final output path: `/home/user/Desktop/image.docx`."
)
assert paths == ["/home/user/Desktop/image.docx"]

print("[OK] Harness and all artifact-validation helpers import.")
print("[OK] Settings and basic output-path extraction verified.")
"""

    print(
        common.capture(
            runtime.command(
                "python",
                "-c",
                import_code,
            )
        )
    )

    help_text = common.capture(
        runtime.command(
            "harbor",
            "run",
            "--help",
        )
    )

    help_text = re.sub(
        r"\x1b\[[0-?]*[ -/]*[@-~]",
        "",
        help_text,
    )

    for flag in [
        "--agent-import-path",
        "-p",
        "-m",
        "-o",
        "-n",
        "-k",
        "-r",
    ]:
        if not re.search(
            rf"(?<![\w-]){re.escape(flag)}(?![\w-])",
            help_text,
        ):
            raise RuntimeError(
                f"Installed Harbor does not expose {flag}."
            )

    print(
        "[OK] Harbor custom-agent command option verified."
    )

    probe_code = """
import subprocess
import sys
from pathlib import Path

source, image, platform = sys.argv[1:]

actual = subprocess.check_output([
    "docker", "run", "--rm",
    "--platform", platform,
    "--mount",
    f"type=bind,source={source},target=/probe.txt,readonly",
    image, "python", "-c",
    "from pathlib import Path; import sys;"
    "sys.stdout.buffer.write(Path('/probe.txt').read_bytes())"
])

if actual != Path(source).read_bytes():
    raise RuntimeError("Task file differs between containers.")

print("[OK] Sibling container can read the task instruction.")
"""

    instruction_path = str(
        PurePosixPath(
            runtime.task_path(tasks[0])
        ) / "instruction.md"
    )

    print(
        common.capture(
            runtime.command(
                "python",
                "-c",
                probe_code,
                instruction_path,
                runtime.image,
                runtime.platform,
            )
        )
    )

    return budgets


def create_summary(raw_directory, record, path, key):
    """Extract official outcomes and harness instrumentation."""
    summary = common.create_summary(
        raw_directory,
        record,
        path,
        key,
    )

    summary["phase"] = record["config"]["phase"]
    summary["task_budget"] = record["task_budget"]

    trial_candidates = [
        item["data"]
        for item in summary.get(
            "harbor_result_records",
            [],
        )
        if isinstance(
            item.get("data"),
            dict,
        )
        and "task_name" in item["data"]
    ]

    metadata = {}

    if len(trial_candidates) == 1:
        agent_result = (
            trial_candidates[0].get("agent_result")
            or {}
        )

        if isinstance(agent_result, dict):
            candidate = agent_result.get(
                "metadata"
            )

            if isinstance(candidate, dict):
                metadata = candidate

    summary["agent_metadata"] = metadata

    for field in [
        "idle_response_guard",
        "artifact_validation",
        "diagnostic_recovery",
    ]:
        summary[field] = metadata.get(field)

    # An execution exception and an official reward may coexist.
    has_reward = (
        common.numeric(
            summary.get("official_reward")
        ) is not None
    )

    summary["has_official_reward"] = has_reward

    warnings = list(
        summary.get("extraction_warnings")
        or []
    )

    if has_reward:
        obsolete_warnings = {
            (
                "No valid graded outcome. "
                "Do not convert this to reward 0."
            ),
            (
                "No valid graded outcome. "
                "Do not silently convert this to reward 0."
            ),
        }

        warnings = [
            warning
            for warning in warnings
            if warning not in obsolete_warnings
        ]

    if summary["idle_response_guard"] is None:
        warnings.append(
            "Idle-guard metadata was not found; "
            "do not assume the guard ran or triggered."
        )

    if summary["artifact_validation"] is None:
        warnings.append(
            "Artifact-validation metadata was not found; "
            "do not assume checks ran or passed."
        )

    if summary["diagnostic_recovery"] is None:
        warnings.append(
            "Diagnostic-recovery metadata was not found; "
            "do not assume a reminder was sent."
        )

    summary["extraction_warnings"] = warnings

    return common.write_json(
        path,
        summary,
        key,
    )


def run_one(
    runtime,
    config,
    assets,
    commit,
    budgets,
    directory,
    attempt_id,
    key,
    source_hashes,
):
    """Run one task once and export its combined result JSON."""
    task = config["task"]

    if harness_hashes() != source_hashes:
        raise RuntimeError(
            "Harness source changed during the batch. "
            "Restore it before continuing."
        )

    remote_run = (
        PurePosixPath(runtime.shared_root)
        / ".pe6203-runs"
        / attempt_id
    )

    jobs_path = str(
        remote_run / "jobs"
    )
    tmp_path = str(
        remote_run / "tmp"
    )

    container_name = f"pe6203-{attempt_id}"
    result_path = (
        directory / task / "result.json"
    )

    if result_path.parent.exists():
        raise RuntimeError(
            "Attempt directory already exists: "
            f"{result_path.parent}"
        )

    result_path.parent.mkdir(
        parents=True
    )

    harbor_command = [
        "harbor",
        "run",
        "-p",
        runtime.task_path(task),
        "--agent-import-path",
        AGENT,
        "-m",
        config["model"],
        "-o",
        jobs_path,
        "-n",
        "1",
        "-k",
        "1",
        "-r",
        "0",
    ]

    record = {
        "purpose": (
            "Bounded evidence and diagnostic harness experiment"
        ),
        "run_id": attempt_id,
        "benchmark_commit": commit,
        "image_id": assets["image_id"],
        "platform": assets["platform"],
        "config": config,
        "task_budget": budgets[task],
        "harness_sha256": source_hashes,
        "harbor_command": harbor_command,
        "runtime_container": container_name,
        "runtime_exit_code": None,
    }

    common.write_json(
        result_path,
        {
            "schema_version": "1.0",
            "run_id": attempt_id,
            "task_id": task,
            "status": "preparing",
            "official_reward": None,
            "reproduction": record,
        },
        key,
    )

    common.capture(
        runtime.command(
            "python",
            "-c",
            "from pathlib import Path; import sys;"
            "[Path(p).mkdir(parents=True,exist_ok=True)"
            " for p in sys.argv[1:]]",
            jobs_path,
            tmp_path,
        )
    )

    common.write_json(
        result_path,
        {
            "schema_version": "1.0",
            "run_id": attempt_id,
            "task_id": task,
            "status": "running",
            "official_reward": None,
            "reproduction": record,
        },
        key,
    )

    environment = os.environ.copy()
    environment["OPENROUTER_API_KEY"] = key

    # Preserve the mounted-log permissions fix.
    command = runtime.command(
        "python",
        "-c",
        "import os,sys; os.umask(0);"
        "os.execvp(sys.argv[1],sys.argv[1:])",
        *harbor_command,
        name=container_name,
        tmp=tmp_path,
    )

    print(
        "Starting one paid model attempt.",
        flush=True,
    )

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
        )
        exit_code = completed.returncode

    except KeyboardInterrupt:
        subprocess.run(
            [
                "docker",
                "stop",
                container_name,
            ],
            cwd=ROOT,
            check=False,
        )

        exit_code = 130

        print(
            "Interrupted. Inspect Docker for "
            "remaining task containers."
        )

    record["runtime_exit_code"] = exit_code

    with TemporaryDirectory(
        prefix="pe6203-bounded-"
    ) as temporary:
        raw_directory = (
            Path(temporary) / "jobs"
        )

        exported = subprocess.run(
            [
                "docker",
                "cp",
                f"{container_name}:{jobs_path}",
                str(raw_directory),
            ],
            cwd=ROOT,
            check=False,
        )

        record["results_exported"] = (
            exported.returncode == 0
        )

        if exported.returncode != 0:
            summary = {
                "schema_version": "1.0",
                "run_id": attempt_id,
                "task_id": task,
                "status": "export_error",
                "official_reward": None,
                "runtime_exit_code": exit_code,
                "reproduction": record,
            }

            common.write_json(
                result_path,
                summary,
                key,
            )

        else:
            summary = create_summary(
                raw_directory,
                record,
                result_path,
                key,
            )

    print(f"Result: {result_path}")
    print(f"Status: {summary['status']}")
    print(
        f"Official reward: {summary['official_reward']}"
    )

    artifact_report = summary.get(
        "artifact_validation"
    )

    if isinstance(artifact_report, dict):
        print(
            "Artifact checks performed: "
            f"{artifact_report.get('checks_performed')}"
        )
        print(
            "Artifact checks skipped: "
            f"{artifact_report.get('checks_skipped')}"
        )
        print(
            "Artifact checker errors: "
            f"{artifact_report.get('checker_errors')}"
        )

    else:
        print(
            "Artifact-check metadata: unavailable"
        )

    diagnostic = summary.get(
        "diagnostic_recovery"
    )

    if isinstance(diagnostic, dict):
        print(
            "Diagnostic reminder sent: "
            f"{diagnostic.get('reminder_sent')}"
        )

    print(
        f"Retained runtime: {container_name}"
    )

    return summary, exit_code


def batch_totals(entries, expected):
    """Calculate totals without inventing missing measurements."""
    rewarded = [
        entry
        for entry in entries
        if common.numeric(
            entry.get("official_reward")
        ) is not None
    ]

    costs = [
        common.numeric(
            entry.get("cost_usd")
        )
        for entry in entries
    ]

    complete = (
        len(entries) == expected
        and len(rewarded) == expected
    )

    return {
        "expected_tasks": expected,
        "recorded_tasks": len(entries),
        "tasks_with_official_reward": len(rewarded),
        "tasks_with_exceptions": sum(
            entry.get(
                "has_exception",
                False,
            )
            for entry in entries
        ),
        "complete_reward_coverage": complete,
        "mean_reward": (
            sum(
                entry["official_reward"]
                for entry in rewarded
            ) / expected
            if complete
            else None
        ),
        "available_reward_mean": (
            sum(
                entry["official_reward"]
                for entry in rewarded
            ) / len(rewarded)
            if rewarded
            else None
        ),
        "known_cost_usd": sum(
            cost
            for cost in costs
            if cost is not None
        ),
        "total_cost_usd": (
            sum(costs)
            if len(entries) == expected
            and all(
                cost is not None
                for cost in costs
            )
            else None
        ),
        "note": (
            "Use actual official rewards, including timeout rewards. "
            "Never replace unavailable rewards with zero. "
            "Available-reward mean is provisional "
            "if coverage is incomplete."
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--phase",
        choices=[
            "development",
            "evaluation",
        ],
        default="evaluation",
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "Run runtime and coverage checks "
            "without model calls."
        ),
    )

    parser.add_argument(
        "--batch-id"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
    )

    args = parser.parse_args()

    if args.resume and not args.batch_id:
        parser.error(
            "--resume requires --batch-id"
        )

    if args.batch_id and not re.fullmatch(
        r"[A-Za-z0-9_-]{1,80}",
        args.batch_id,
    ):
        parser.error(
            "Invalid batch ID."
        )

    baseline = common.read_json(
        ROOT / "configs" / "baseline.json"
    )
    selection = common.read_json(
        ROOT / "manifests" / "task_selection.json"
    )
    benchmark = common.read_json(
        ROOT / "manifests" / "benchmark.json"
    )
    assets = common.read_json(
        ROOT / ".cache" / "runtime" / "asset_info.json"
    )

    tasks = selected_tasks(
        selection,
        args.phase,
    )
    commit = benchmark["commit"]

    if (
        selection["benchmark_commit"] != commit
        or assets["benchmark_commit"] != commit
    ):
        raise ValueError(
            "Benchmark versions do not match."
        )

    model = baseline.get("model")

    if (
        not isinstance(model, str)
        or not model.startswith("openrouter/")
        or not model.removeprefix(
            "openrouter/"
        ).strip()
    ):
        raise ValueError(
            "Invalid model in configs/baseline.json."
        )

    for field, expected in {
        "attempts": 1,
        "concurrency": 1,
        "trial_retries": 0,
    }.items():
        if baseline.get(field) != expected:
            raise ValueError(
                f"{field} must be {expected}."
            )

    config = dict(baseline)
    config.pop("task", None)

    config.update({
        "agent": AGENT,
        "configuration_id": (
            "cheap-bounded-evidence-diagnostic"
        ),
        "variant": VARIANT,
        "phase": args.phase,
        "repeat": 1,
        "components": {
            "custom_context_management": False,
            "custom_failure_recovery": True,
            "idle_response_guard": True,
            "conditional_recovery_reminder": True,
            "pre_submission_artifact_validation": True,
            "completion_evidence_guidance": True,
            "conditional_diagnostic_reminder": True,
            "unconditional_recovery_guidance": False,
        },
        "idle_response_limit": 3,
        "recovery_reminder_at": 2,
        "max_recovery_reminders_per_task": 1,
        "artifact_validation": {
            "max_checks": 2,
            "max_paths_per_check": 100,
            "execution_timeout_sec": 30,
            "scope": (
                "Explicit outputs, public JSON declarations, "
                "accepted filename alternatives, Python syntax, "
                "image rename integrity, and basic browser-PDF checks"
            ),
            "feedback": (
                "Existing completion-confirmation turn"
            ),
            "semantic_correctness_checked": False,
        },
    })

    source_hashes = harness_hashes()
    runtime = Runtime(assets)

    print(f"Variant: {VARIANT}")
    print(f"Model: {model}")
    print(
        f"Phase: {args.phase} | Tasks: {len(tasks)} "
        "| Attempts per task: 1 | Sequential execution"
    )

    budgets = preflight(
        runtime,
        tasks,
        commit,
    )

    coverage = check_output_coverage(
        runtime,
        tasks,
    )

    if args.check_only:
        print(
            "\nRuntime preflight passed. "
            "Coverage warnings, if any, are non-blocking."
        )
        print(
            "No model calls or result files created."
        )
        print(
            "This does not establish task accuracy, "
            "complete validation coverage, or spending limits."
        )
        return 0

    plan = {
        "tasks": tasks,
        "config": config,
        "benchmark_commit": commit,
        "image_id": assets["image_id"],
        "platform": assets["platform"],
        "harness_sha256": source_hashes,
        "runner_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "shared_helpers_sha256": hashlib.sha256(
            Path(common.__file__).read_bytes()
        ).hexdigest(),
        "output_coverage": coverage,
    }

    batch_id = args.batch_id or (
        f"bounded-diagnostic-{args.phase}-"
        + datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        + "-"
        + uuid.uuid4().hex[:8]
    )

    directory = (
        ROOT / "results" / batch_id
    )
    index_path = (
        directory / "batch_summary.json"
    )

    if directory.exists():
        if not args.resume:
            raise ValueError(
                "Batch exists; choose a new ID."
            )

        if (
            common.read_json(
                index_path
            ).get("plan") != plan
        ):
            raise ValueError(
                "Resume settings or source code changed. "
                "Restore the original settings/code "
                "or start a new batch."
            )

    elif args.resume:
        raise ValueError(
            "Batch does not exist."
        )

    key = common.load_api_key()

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        f"Batch ID: {batch_id}",
        flush=True,
    )
    print(
        "API charges apply.",
        flush=True,
    )

    def save_index():
        entries = []

        for task in tasks:
            path = (
                directory / task / "result.json"
            )

            if not path.exists():
                continue

            summary = common.read_json(path)
            usage = (
                summary.get("usage") or {}
            )

            entries.append({
                "task_id": task,
                "status": summary.get("status"),
                "official_reward": summary.get(
                    "official_reward"
                ),
                "has_exception": bool(
                    summary.get("exception")
                ),
                "runtime_exit_code": summary.get(
                    "runtime_exit_code"
                ),
                "cost_usd": usage.get(
                    "reported_total_cost_usd"
                ),
                "input_tokens": usage.get(
                    "reported_input_tokens"
                ),
                "output_tokens": usage.get(
                    "reported_output_tokens"
                ),
                "cache_tokens": usage.get(
                    "reported_cache_tokens"
                ),
                "idle_response_guard": summary.get(
                    "idle_response_guard"
                ),
                "artifact_validation": summary.get(
                    "artifact_validation"
                ),
                "diagnostic_recovery": summary.get(
                    "diagnostic_recovery"
                ),
                "result_path": path.relative_to(
                    directory
                ).as_posix(),
            })

        totals = batch_totals(
            entries,
            len(tasks),
        )

        common.write_json(
            index_path,
            {
                "schema_version": "1.0",
                "batch_id": batch_id,
                "plan": plan,
                "tasks": entries,
                "totals": totals,
            },
            key,
        )

        return totals

    try:
        save_index()

        for number, task in enumerate(
            tasks,
            1,
        ):
            path = (
                directory / task / "result.json"
            )

            if path.exists():
                saved = common.read_json(path)

                if saved.get("status") in {
                    "running",
                    "preparing",
                }:
                    raise RuntimeError(
                        f"{task} has an unresolved attempt. "
                        "Inspect its retained runtime first."
                    )

                print(
                    f"[SKIP {number}/{len(tasks)}] {task}"
                )
                continue

            print(
                f"\n[RUN {number}/{len(tasks)}] {task}",
                flush=True,
            )

            current = dict(
                config,
                task=task,
                batch_id=batch_id,
            )

            attempt_id = (
                f"{batch_id}-{number:02d}"
            )

            try:
                summary, exit_code = run_one(
                    runtime,
                    current,
                    assets,
                    commit,
                    budgets,
                    directory,
                    attempt_id,
                    key,
                    source_hashes,
                )

            except (
                OSError,
                ValueError,
                KeyError,
                RuntimeError,
                TypeError,
                subprocess.SubprocessError,
            ) as error:
                saved = (
                    common.read_json(path)
                    if path.exists()
                    else {
                        "schema_version": "1.0",
                        "task_id": task,
                        "status": "runner_error",
                        "official_reward": None,
                        "reproduction": {
                            "config": current
                        },
                    }
                )

                saved["runner_error"] = str(error)

                common.write_json(
                    path,
                    saved,
                    key,
                )

                save_index()
                raise

            save_index()

            # Coverage warnings do not stop task execution.
            # Actual execution/export/verification problems still do.
            if (
                exit_code != 0
                or summary.get("exception")
                or summary.get("status") != "graded"
            ):
                print(
                    "Batch stopped for an execution, export, "
                    "or verification problem. "
                    "Resume skips recorded terminal errors."
                )

                return (
                    130
                    if exit_code == 130
                    else 1
                )

        totals = save_index()

        print(
            f"\nBatch summary: {index_path}"
        )
        print(
            json.dumps(
                totals,
                indent=2,
            )
        )

        return (
            0
            if totals["complete_reward_coverage"]
            else 1
        )

    finally:
        common.print_remaining_credits(key)


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(
                error.stdout,
                file=sys.stderr,
            )

        if error.stderr:
            print(
                error.stderr,
                file=sys.stderr,
            )

        print(
            "[FAIL] Docker or preflight failed.",
            file=sys.stderr,
        )

        raise SystemExit(1)

    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(
            f"[FAIL] {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    except KeyboardInterrupt:
        print(
            "\nStopped by user.",
            file=sys.stderr,
        )
        raise SystemExit(130)