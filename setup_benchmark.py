"""Download the pinned benchmark and preserve the shared task selection."""

import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
BENCHMARK = ROOT / "vendor" / "TUA-Bench"
MANIFESTS = ROOT / "manifests"
REPOSITORY = "https://github.com/facebookresearch/TUA-Bench.git"


def git(*arguments):
    result = subprocess.run(
        ["git", "-C", str(BENCHMARK), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=True,
    )
    return result.stdout.strip()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    benchmark_path = MANIFESTS / "benchmark.json"
    selection_path = MANIFESTS / "task_selection.json"

    # All teammates must use the benchmark version committed to GitHub.
    if not benchmark_path.is_file():
        raise RuntimeError(
            "manifests/benchmark.json is missing. "
            "Retrieve the shared manifest from GitHub first."
        )

    benchmark_info = read_json(benchmark_path)

    if benchmark_info.get("repository") != REPOSITORY:
        raise RuntimeError("Unexpected benchmark repository in manifest.")

    commit = benchmark_info["commit"]
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(char not in "0123456789abcdef" for char in commit)
    ):
        raise RuntimeError("Invalid benchmark commit.")

    if not BENCHMARK.exists():
        BENCHMARK.parent.mkdir(parents=True, exist_ok=True)

        print("Downloading official TUA-Bench...", flush=True)
        subprocess.run(
            [
                "git", "clone",
                "-c", "core.autocrlf=false",
                REPOSITORY,
                str(BENCHMARK),
            ],
            check=True,
            timeout=600,
        )

        git("checkout", "--detach", commit)

    if not (BENCHMARK / ".git").is_dir():
        raise RuntimeError(
            "Benchmark directory exists but is not a Git clone. "
            "No files were overwritten."
        )

    if git("remote", "get-url", "origin").rstrip("/") != REPOSITORY:
        raise RuntimeError("Unexpected benchmark origin.")

    if git("rev-parse", "HEAD") != commit:
        raise RuntimeError(
            "Local benchmark version differs from the shared manifest. "
            "No reset or overwrite was performed."
        )

    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError(
            "Tracked benchmark files have local changes. "
            "Official task files must remain unchanged."
        )

    task_ids = sorted(
        path.name
        for path in (BENCHMARK / "tasks").iterdir()
        if path.is_dir() and (path / "task.toml").is_file()
    )

    if len(task_ids) != 120:
        raise RuntimeError(
            f"Expected 120 official tasks; found {len(task_ids)}."
        )

    available = set(task_ids)

    if selection_path.exists():
        # Never replace a teammate's committed selection.
        selection = read_json(selection_path)
        print("Using existing shared task selection.")
    else:
        # Recover this project's original deterministic selection.
        shuffled = task_ids.copy()
        random.Random(6203).shuffle(shuffled)

        selection = {
            "benchmark_commit": commit,
            "seed": 6203,
            "method": (
                "Shuffle sorted task IDs; first 40 for evaluation, "
                "next 5 for development."
            ),
            "evaluation": sorted(shuffled[:40]),
            "development": sorted(shuffled[40:45]),
        }
        print("Reconstructing selection using the original seed: 6203.")

    if selection.get("benchmark_commit") != commit:
        raise RuntimeError("Task selection uses another benchmark version.")

    selected = {}

    for name, expected in [("evaluation", 40), ("development", 5)]:
        ids = selection.get(name)

        if (
            not isinstance(ids, list)
            or not all(isinstance(task_id, str) for task_id in ids)
        ):
            raise RuntimeError(f"Invalid {name} task list.")

        if len(ids) != expected or len(set(ids)) != expected:
            raise RuntimeError(
                f"Expected {expected} unique {name} task IDs."
            )

        missing = set(ids) - available
        if missing:
            raise RuntimeError(f"Unknown {name} task IDs: {sorted(missing)}")

        selected[name] = set(ids)

    if selected["evaluation"] & selected["development"]:
        raise RuntimeError("Evaluation and development tasks overlap.")

    if not selection_path.exists():
        write_json(selection_path, selection)

    print()
    print("[OK] Official benchmark downloaded and version verified.")
    print("[OK] Official tasks: 120")
    print("[OK] Evaluation selection: 40 unique tasks")
    print("[OK] Development selection: 5 separate tasks")
    print("No benchmark tasks or model API calls were executed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        raise SystemExit(1)