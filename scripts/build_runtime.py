"""Build the runtime if needed, then verify it."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "pe6203-runtime:local"
PLATFORM = "linux/amd64"


def run(command, timeout=180):
    """Run a command, capturing output for inspection."""
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=True,
    ).stdout.strip()


def runtime_command(*arguments, docker_access=False):
    command = [
        "docker", "run", "--rm",
        "--platform", PLATFORM,
    ]

    if docker_access:
        command.extend([
            "--mount",
            "type=bind,source=/var/run/docker.sock,"
            "target=/var/run/docker.sock",
        ])

    return [*command, IMAGE, *arguments]


def inspect_image():
    """Return image metadata, or None if the image does not exist."""
    # Distinguish an unavailable Docker engine from a missing image.
    run(["docker", "info"])

    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    if result.returncode != 0:
        message = result.stderr.strip()
        if "no such image" in message.lower():
            return None
        raise RuntimeError(f"Cannot inspect runtime image: {message}")

    return json.loads(result.stdout)[0]


def build_image(commit):
    print("Building runtime image...", flush=True)

    subprocess.run(
        [
            "docker", "build",
            "--platform", PLATFORM,
            "--build-arg", f"BENCHMARK_COMMIT={commit}",
            "--tag", IMAGE,
            "--file", str(ROOT / "docker" / "Dockerfile"),
            str(ROOT / "docker"),
        ],
        cwd=ROOT,
        check=True,
    )


def verify_runtime(commit):
    print("\nChecking runtime...", flush=True)

    actual_commit = run(
        runtime_command("git", "rev-parse", "HEAD")
    )
    if actual_commit != commit:
        raise RuntimeError(
            "Image benchmark version differs from the manifest. "
            "Run again with --rebuild."
        )
    print("[OK] Benchmark commit matches.")

    versions = json.loads(run(runtime_command(
        "python", "-c",
        "import json, platform, importlib.metadata as m;"
        "print(json.dumps({"
        "'python': platform.python_version(),"
        "'harbor': m.version('harbor')"
        "}))",
    )))

    print(f"[OK] Container Python: {versions['python']}")
    print(f"[OK] Container Harbor: {versions['harbor']}")

    help_text = run(runtime_command("harbor", "run", "--help"))
    print("[OK] Harbor run command loads.")

    server_os = run(runtime_command(
        "docker", "version", "--format", "{{.Server.Os}}",
        docker_access=True,
    ))
    if server_os != "linux":
        raise RuntimeError("Docker engine must use Linux containers.")
    print("[OK] Runtime can access Docker engine.")

    compose_version = run(runtime_command(
        "docker", "compose", "version",
        docker_access=True,
    ))
    print(f"[OK] {compose_version}")

    hello_output = run(runtime_command(
        "docker", "run", "--rm",
        "--platform", PLATFORM,
        "hello-world",
        docker_access=True,
    ))
    if "Hello from Docker!" not in hello_output:
        raise RuntimeError("Test container did not return expected output.")
    print("[OK] Runtime can launch a separate test container.")

    evidence_dir = ROOT / ".cache" / "runtime"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    (evidence_dir / "harbor_run_help.txt").write_text(
        help_text + "\n", encoding="utf-8"
    )

    image = inspect_image()
    evidence = {
        "image": IMAGE,
        "image_id": image["Id"],
        "platform": PLATFORM,
        "benchmark_commit": actual_commit,
        "compose": compose_version,
        **versions,
    }

    (evidence_dir / "build_info.json").write_text(
        json.dumps(evidence, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[OK] Verification evidence saved: {evidence_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the image even if it already exists.",
    )
    args = parser.parse_args()

    manifest_path = ROOT / "manifests" / "benchmark.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    commit = manifest["commit"]

    if not isinstance(commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}", commit
    ):
        raise RuntimeError("Invalid benchmark commit in manifest.")

    image = inspect_image()

    if image is None or args.rebuild:
        build_image(commit)
    else:
        print(f"Using existing image: {IMAGE}")
        print("Use --rebuild after changing the Dockerfile.")

    verify_runtime(commit)

    print("\nAll runtime checks passed.")
    print("No benchmark tasks or model API calls were executed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        print("[FAIL] Runtime command failed.", file=sys.stderr)
        raise SystemExit(1)
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        raise SystemExit(1)