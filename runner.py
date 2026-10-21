"""Check the local tools required for the PE6203 project."""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent


def check_tasks():
    """Read and validate task files without changing anything."""
    failures = []
    task_root = PROJECT_ROOT / "vendor" / "TUA-Bench" / "tasks"
    selection_path = PROJECT_ROOT / "manifests" / "task_selection.json"

    if not task_root.is_dir():
        print("[FAIL] Benchmark task directory not found.")
        return ["Benchmark tasks are missing."]

    available = {
        path.name
        for path in task_root.iterdir()
        if path.is_dir() and (path / "task.toml").is_file()
    }

    if len(available) == 120:
        print("[OK] Downloaded benchmark tasks: 120")
    else:
        print(f"[FAIL] Downloaded benchmark tasks: {len(available)}")
        failures.append("Expected 120 downloaded tasks.")

    try:
        selection = json.loads(
            selection_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        print(f"[FAIL] Cannot read task selection: {error}")
        return failures + ["Task selection is missing or invalid."]

    if not isinstance(selection, dict):
        return failures + ["Task selection must be a JSON object."]

    selected_sets = {}

    for key, expected in [("evaluation", 40), ("development", 5)]:
        task_ids = selection.get(key)

        if (
            not isinstance(task_ids, list)
            or not all(isinstance(task_id, str) for task_id in task_ids)
        ):
            print(f"[FAIL] {key}: expected a list of task IDs.")
            failures.append(f"Invalid {key} task list.")
            continue

        unique_ids = set(task_ids)
        selected_sets[key] = unique_ids

        if len(task_ids) != expected:
            print(f"[FAIL] {key} tasks: {len(task_ids)}; expected {expected}.")
            failures.append(f"Incorrect {key} task count.")
        elif len(unique_ids) != len(task_ids):
            print(f"[FAIL] {key} contains duplicate task IDs.")
            failures.append(f"Duplicate {key} tasks.")
        else:
            print(f"[OK] Selected {key} tasks: {expected} unique IDs")

        missing = unique_ids - available
        if missing:
            print(f"[FAIL] {key} IDs not found: {', '.join(sorted(missing))}")
            failures.append(f"Missing {key} tasks.")
        else:
            print(f"[OK] All {key} IDs exist in the benchmark.")

    if {"evaluation", "development"} <= selected_sets.keys():
        overlap = selected_sets["evaluation"] & selected_sets["development"]
        if overlap:
            print(f"[FAIL] Evaluation/development overlap: {sorted(overlap)}")
            failures.append("Evaluation and development tasks overlap.")
        else:
            print("[OK] Evaluation and development sets do not overlap.")

    return failures


def check_environment():
    print(f"Project: {PROJECT_ROOT}")
    print(f"System:  {platform.system()} {platform.machine()}")
    print(f"Python:  {platform.python_version()}")
    print()

    failures = []

    if sys.version_info < (3, 11):
        failures.append("Python 3.11 or newer is required.")

    checks = [
        ("Git", ["git", "--version"]),
        (
            "Docker engine",
            [
                "docker",
                "version",
                "--format",
                "{{.Server.Os}}/{{.Server.Arch}}",
            ],
        ),
        ("Docker Compose", ["docker", "compose", "version"]),
    ]

    for label, command in checks:
        if shutil.which(command[0]) is None:
            print(f"[FAIL] {label}: executable not found.")
            failures.append(label)
            continue

        try:
            result = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"[FAIL] {label}: {error}")
            failures.append(label)
            continue

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            print(f"[FAIL] {label}: {message}")
            failures.append(label)
            continue

        output = result.stdout.strip()
        print(f"[OK] {label}: {output}")

        if label == "Docker engine" and not output.startswith("linux/"):
            failures.append("Docker must use Linux containers.")

    # Run task checks once, after all tool checks.
    print()
    failures.extend(check_tasks())
    print()

    if failures:
        print("Checks failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("Environment checks passed.")
    print("No files were changed, tasks executed, or model APIs called.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "setup"])
    args = parser.parse_args()

    if args.command == "setup":
        setup_script = PROJECT_ROOT / "setup_benchmark.py"

        if not setup_script.is_file():
            print("[FAIL]/setup_benchmark.py is missing.")
            return 1

        result = subprocess.run(
            [sys.executable, str(setup_script)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        return result.returncode

    return check_environment()


if __name__ == "__main__":
    raise SystemExit(main())