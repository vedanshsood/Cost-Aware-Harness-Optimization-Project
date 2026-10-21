"""Check and execute one default-harness TUA-Bench task."""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path, PurePosixPath
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def capture(command):
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=True,
    ).stdout.strip()


def load_api_key():
    """Read the key without printing it or placing it in command arguments."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()

    if not key:
        env_path = ROOT / ".env"
        if env_path.is_file():
            for line in env_path.read_text(
                encoding="utf-8-sig"
            ).splitlines():
                name, separator, value = line.strip().partition("=")
                if separator and name == "OPENROUTER_API_KEY":
                    key = value.strip().strip("\"'")
                    break

    if not key or key == "replace_with_your_actual_key":
        raise RuntimeError(
            "Set OPENROUTER_API_KEY in the root .env file."
        )

    return key

def print_remaining_credits(key):
    """Display key allowance without exposing credentials."""
    print("\nOpenRouter key balance:")

    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)["data"]

        remaining = data.get("limit_remaining")
        limit = data.get("limit")
        usage = data.get("usage")

        if remaining is not None:
            print(f"Remaining key allowance: US${remaining:.4f}")
        elif limit is None:
            print("No individual spending limit is set for this key.")
            print("Account credit balance is not available from this endpoint.")
        else:
            print("Remaining key allowance was not returned.")

        if usage is not None:
            print(f"Reported cumulative key usage: US${usage:.4f}")

        reset = data.get("limit_reset")
        if reset:
            print(f"Key allowance reset interval: {reset}")

        print("This is key-level information, not the account credit balance.")

    except urllib.error.HTTPError as error:
        print(f"Balance unavailable: HTTP {error.code}.")
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ):
        print("Balance unavailable: connection or response error.")


def numeric(value):
    """Missing or invalid measurements remain null, never zero."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return value if math.isfinite(value) else None
        except OverflowError:
            return None
    return None


def duration(timing):
    if not isinstance(timing, dict):
        return None
    start, end = timing.get("started_at"), timing.get("finished_at")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        seconds = (end - start).total_seconds()
        return seconds if seconds >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def write_json(path, payload, api_key=None):
    """Redact the active key, including its JSON-escaped representation."""
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    if api_key:
        serialized = serialized.replace(
            json.dumps(api_key, ensure_ascii=False)[1:-1], "[REDACTED]"
        ).replace(api_key, "[REDACTED]")
    path.write_text(serialized + "\n", encoding="utf-8")
    return json.loads(serialized)


def create_summary(raw_directory, record, output_path, api_key=None):
    """Combine one Harbor attempt and its text evidence into one JSON."""
    warnings, evidence, binary_files = [], {}, []
    for path in sorted(raw_directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(raw_directory).as_posix()
        try:
            evidence[relative] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            binary_files.append(relative)

    result_records, trial_candidates = [], []
    for path in sorted(raw_directory.rglob("result.json")):
        relative = path.relative_to(raw_directory).as_posix()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            warnings.append(f"Cannot parse {relative}.")
            continue
        if not isinstance(payload, dict):
            continue
        result_records.append({"path": relative, "data": payload})
        if "task_name" in payload or (
            (path.parent / "agent").is_dir()
            or (path.parent / "exception.txt").is_file()
        ):
            trial_candidates.append(payload)

    trial = {}
    if len(trial_candidates) == 1:
        trial = trial_candidates[0]
    else:
        warnings.append(f"Expected one trial result; found {len(trial_candidates)}.")
    agent = trial.get("agent_result") or {}
    verifier = trial.get("verifier_result") or {}
    exception = trial.get("exception_info")
    if not isinstance(agent, dict):
        agent = {}
    if not isinstance(verifier, dict):
        verifier = {}
    rewards, reward = verifier.get("rewards"), None
    if isinstance(rewards, dict):
        if "reward" in rewards:
            reward = numeric(rewards["reward"])
        elif len(rewards) == 1:
            reward = numeric(next(iter(rewards.values())))
        else:
            warnings.append("Multiple reward fields; choose a primary metric.")
    if exception:
        status = "execution_error"
        if "RewardFileNotFoundError" in json.dumps(exception):
            status = "verification_error"
    elif reward is not None:
        status = "graded"
    else:
        status = "ungraded"
    if status != "graded":
        warnings.append("No valid graded outcome. Do not silently convert this to reward 0.")
    cost = numeric(agent.get("cost_usd"))
    if cost is None:
        warnings.append("Total cost unavailable from agent_result.cost_usd; inspect embedded records before using cost plots.")
    trajectories = {}
    for name, text in evidence.items():
        if name.endswith("trajectory.json"):
            try:
                trajectories[name] = json.loads(text)
            except ValueError:
                warnings.append(f"Cannot parse trajectory: {name}")
    config = record["config"]
    summary = {
        "schema_version": "1.0",
        "run_id": record["run_id"],
        "task_id": config["task"],
        "configuration_id": config.get("configuration_id"),
        "variant": config.get("variant", "default"),
        "repeat": config.get("repeat", 1),
        "phase": config.get("phase", "smoke_test"),
        "components": config.get("components", {}),
        "agent": config["agent"], "model": config["model"],
        "provider": "openrouter",
        "benchmark_commit": record["benchmark_commit"],
        "image_id": record["image_id"], "platform": record["platform"],
        "status": status, "official_reward": reward,
        "official_rewards": rewards, "exception": exception,
        "runtime_exit_code": record.get("runtime_exit_code"),
        "timing": {
            "trial_seconds": duration(trial),
            "agent_seconds": duration(trial.get("agent_execution")),
            "verifier_seconds": duration(trial.get("verifier_execution")),
        },
        "usage": {
            "reported_input_tokens": numeric(agent.get("n_input_tokens")),
            "reported_output_tokens": numeric(agent.get("n_output_tokens")),
            "reported_cache_tokens": numeric(agent.get("n_cache_tokens")),
            "reported_total_cost_usd": cost,
            "source": "Harbor trial agent_result",
            "agent_inference": {"input_tokens": None, "output_tokens": None, "cost_usd": None},
            "harness_overhead": {"input_tokens": None, "output_tokens": None, "cost_usd": None},
        },
        "failure_review": {"category": None, "reason": None, "reviewed": False},
        "reproduction": record,
        "harbor_trial_config": trial.get("config"),
        "trajectories": trajectories,
        "harbor_result_records": result_records,
        "text_logs": evidence,
        "binary_files_not_embedded": binary_files,
        "extraction_warnings": warnings,
    }
    return write_json(output_path, summary, api_key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate setup without calling the model.",
    )
    args = parser.parse_args()

    config = read_json(ROOT / "configs" / "baseline.json")
    benchmark = read_json(ROOT / "manifests" / "benchmark.json")
    selection = read_json(ROOT / "manifests" / "task_selection.json")
    assets = read_json(ROOT / ".cache" / "runtime" / "asset_info.json")

    task = config["task"]
    image = assets["image"]
    platform = assets["platform"]
    volume = assets["asset_volume"]
    commit = benchmark["commit"]

    if task not in selection["evaluation"]:
        raise RuntimeError("Task is not in the fixed evaluation subset.")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", task):
        raise RuntimeError("Invalid task ID.")

    if config["agent"] != "terminus-2":
        raise RuntimeError("This script requires default Terminus-2.")

    expected = {
        "attempts": 1,
        "concurrency": 1,
        "trial_retries": 0,
    }
    for field, value in expected.items():
        if config.get(field) != value:
            raise RuntimeError(f"{field} must be {value} for this smoke test.")

    if (
        selection["benchmark_commit"] != commit
        or assets["benchmark_commit"] != commit
    ):
        raise RuntimeError("Benchmark versions do not match.")

    image_info = json.loads(
        capture(["docker", "image", "inspect", image])
    )[0]
    if image_info["Id"] != assets["image_id"]:
        raise RuntimeError(
            "Runtime image changed. Run prepare_assets.py again."
        )

    volume_info = json.loads(
        capture(["docker", "volume", "inspect", volume])
    )[0]

    # Use the engine-visible path inside the runtime as well.
    # That allows Harbor-created task containers to mount the same files.
    shared_root = volume_info["Mountpoint"]
    if not shared_root.startswith("/"):
        raise RuntimeError("Expected a Linux Docker volume mountpoint.")

    task_path = str(PurePosixPath(shared_root) / "tasks" / task)

    def runtime(*arguments):
        return [
            "docker", "run", "--rm",
            "--platform", platform,
            "--mount",
            "type=bind,source=/var/run/docker.sock,"
            "target=/var/run/docker.sock",
            "--mount",
            f"type=volume,source={volume},target=/opt/tua-bench",
            "--mount",
            f"type=volume,source={volume},target={shared_root}",
            "--workdir", shared_root,
            image,
            *arguments,
        ]

    # Validate the prepared source and marker without running the task.
    validation_code = """
import json
import subprocess
import sys
from pathlib import Path

expected_commit, task_path = sys.argv[1:]
root = Path("/opt/tua-bench")

actual = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=root, text=True
).strip()

if actual != expected_commit:
    raise RuntimeError("Prepared benchmark commit differs.")

marker = json.loads(
    (root / ".pe6203-assets-ready.json").read_text()
)
if marker.get("benchmark_commit") != expected_commit:
    raise RuntimeError("Assets are not prepared for this commit.")

task = Path(task_path)
for filename in ["instruction.md", "task.toml"]:
    if not (task / filename).is_file():
        raise RuntimeError(f"Missing task file: {filename}")

print((task / "instruction.md").read_text())
"""
    instruction = capture(runtime(
        "python", "-c", validation_code, commit, task_path
    ))
    print(f"Task:  {task}")
    print(f"Agent: {config['agent']}")
    print(f"Model: {config['model']}")
    print("\nOfficial task instruction:\n")
    print(instruction)
    print("\n[OK] Prepared task and benchmark version verified.")

    # Confirm a separate container sees the same instruction bytes.
    instruction_path = str(PurePosixPath(task_path) / "instruction.md")
    probe_code = """
import hashlib
import subprocess
import sys
from pathlib import Path

source, image, platform = sys.argv[1:]
expected = Path(source).read_bytes()

actual = subprocess.check_output([
    "docker", "run", "--rm", "--platform", platform,
    "--mount", f"type=bind,source={source},target=/probe.txt,readonly",
    image, "python", "-c",
    "from pathlib import Path;"
    "import sys;"
    "sys.stdout.buffer.write(Path('/probe.txt').read_bytes())"
])

if hashlib.sha256(actual).digest() != hashlib.sha256(expected).digest():
    raise RuntimeError("Task file differs between containers.")
print("[OK] Separate container can read the same task file.")
"""
    print(capture(runtime(
        "python", "-c", probe_code, instruction_path, image, platform
    )))

    help_text = capture(runtime("harbor", "run", "--help"))
    clean_help = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", help_text)

    for flag in ["-p", "-a", "-m", "-o", "-n", "-k", "-r"]:
        if not re.search(
            rf"(?<![\w-]){re.escape(flag)}(?![\w-])", clean_help
        ):
            raise RuntimeError(
                f"Installed Harbor help does not expose {flag}. "
                "Inspect .cache/runtime/harbor_run_help.txt before running."
            )

    print("[OK] Required Harbor command options found.")

    if args.check_only:
        print("\nPreflight passed. No model API calls were made.")
        return 0

    key = load_api_key()

    run_id = (
        "default-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    container_name = f"pe6203-{run_id}"
    remote_run = str(
        PurePosixPath(shared_root) / ".pe6203-runs" / run_id
    )
    jobs_path = str(PurePosixPath(remote_run) / "jobs")
    temporary_path = str(PurePosixPath(remote_run) / "tmp")

    capture(runtime(
        "python", "-c",
        "from pathlib import Path; import sys;"
        "[Path(p).mkdir(parents=True, exist_ok=True) for p in sys.argv[1:]]",
        jobs_path, temporary_path,
    ))

    harbor_command = [
        "harbor", "run",
        "-p", task_path,
        "-a", config["agent"],
        "-m", config["model"],
        "-o", jobs_path,
        "-n", "1",
        "-k", "1",
        "-r", "0",
    ]

    local_run = ROOT / "results" / run_id
    local_run.mkdir(parents=True, exist_ok=False)

    record = {
        "purpose": "single-task infrastructure smoke test",
        "run_id": run_id,
        "benchmark_commit": commit,
        "image_id": assets["image_id"],
        "platform": platform,
        "config": config,
        "harbor_command": harbor_command,
        "runtime_container": container_name,
    }
    result_path = local_run / "result.json"
    write_json(result_path, {
        "schema_version": "1.0", "run_id": run_id,
        "status": "running", "official_reward": None,
        "reproduction": record,
    }, key)

    environment = os.environ.copy()
    environment["OPENROUTER_API_KEY"] = key

    # Let the non-root task user write to Harbor's mounted output directories.
    # This applies to newly created files/directories in this runtime process.
    command = runtime(
        "python",
        "-c",
        "import os, sys; "
        "os.umask(0); "
        "os.execvp(sys.argv[1], sys.argv[1:])",
        *harbor_command,
    )

    # Replace --rm with execution options without splitting another flag.
    option_index = command.index("--rm")
    command[option_index:option_index + 1] = [
        "--name", container_name,
        "--env", "OPENROUTER_API_KEY",
        "--env", f"TMPDIR={temporary_path}",
        "--env", f"DOCKER_DEFAULT_PLATFORM={platform}",
    ]

    print("\nStarting ONE model-backed attempt. API charges apply.", flush=True)
    print(f"Results destination: {local_run}", flush=True)

    try:
        result = subprocess.run(
            command, cwd=ROOT, env=environment, check=False
        )
        exit_code = result.returncode
    except KeyboardInterrupt:
        subprocess.run(
            ["docker", "stop", container_name],
            cwd=ROOT, check=False,
        )
        exit_code = 130
        print("\nInterrupted. Inspect Docker for any remaining task containers.")

    record["runtime_exit_code"] = exit_code

    # Export raw files temporarily; keep just the combined result locally.
    try:
        with TemporaryDirectory(prefix="pe6203-results-") as temporary:
            raw_directory = Path(temporary) / "jobs"
            export = subprocess.run(
                ["docker", "cp", f"{container_name}:{jobs_path}", str(raw_directory)],
                cwd=ROOT, check=False,
            )
            record["results_exported"] = export.returncode == 0
            if export.returncode != 0:
                write_json(result_path, {
                    "schema_version": "1.0", "run_id": run_id,
                    "status": "export_error", "official_reward": None,
                    "reproduction": record,
                }, key)
                print("Export failed; the runtime container and volume were retained.")
                print(f"Result JSON: {result_path}")
                return exit_code if exit_code != 0 else 1
            summary = create_summary(raw_directory, record, result_path, key)
    except (OSError, ValueError, TypeError) as error:
        write_json(result_path, {
            "schema_version": "1.0", "run_id": run_id,
            "status": "summary_error", "official_reward": None,
            "error": str(error), "reproduction": record,
        }, key)
        print(f"Summary failed. Runtime retained: {container_name}")
        raise
    finally:
        print_remaining_credits(key)

    print(f"\nRuntime exit code: {exit_code}")
    print(f"Result JSON: {result_path}")
    print(f"Status: {summary['status']}")
    print(f"Official reward: {summary['official_reward']}")
    print(f"Reported cost (USD): {summary['usage']['reported_total_cost_usd']}")
    for warning in summary["extraction_warnings"]:
        print(f"[WARN] {warning}")
    print(f"Retained runtime container: {container_name}")
    if exit_code != 0:
        return exit_code
    # Harbor can exit zero even when its trial failed verification.
    return 0 if summary["status"] == "graded" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        print("[FAIL] Preflight or Docker command failed.", file=sys.stderr)
        raise SystemExit(1)
    except (
        OSError, ValueError, KeyError, RuntimeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        raise SystemExit(1)