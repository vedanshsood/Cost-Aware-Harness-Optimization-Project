"""Prepare official TUA-Bench assets in persistent Docker storage."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "pe6203-runtime:local"
PLATFORM = "linux/amd64"


def capture(command):
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=True,
    ).stdout.strip()


def main():
    manifest = json.loads(
        (ROOT / "manifests" / "benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    commit = manifest["commit"]

    image_info = json.loads(
        capture(["docker", "image", "inspect", IMAGE])
    )[0]

    image_id = image_info["Id"]
    image_commit = (
        image_info.get("Config", {})
        .get("Labels", {})
        .get("pe6203.benchmark.commit")
    )

    if image_commit != commit:
        raise RuntimeError(
            "Runtime image does not match the benchmark manifest. "
            "Run scripts/build_runtime.py --rebuild first."
        )

    # A changed runtime image gets separate storage to avoid reusing
    # an older Python environment accidentally.
    image_hash = image_id.split(":")[-1][:12]
    volume = f"pe6203-assets-{commit[:12]}-{image_hash}"

    capture(["docker", "volume", "create", volume])

    print(f"Runtime image: {IMAGE}", flush=True)
    print(f"Asset volume:  {volume}", flush=True)
    print("Preparing official benchmark assets...", flush=True)

    # Docker initially populates this new volume from the image's
    # /opt/tua-bench directory, including its installed environment.
    prepare_code = """
import json
import subprocess
from pathlib import Path

root = Path("/opt/tua-bench")
marker = root / ".pe6203-assets-ready.json"

commit = subprocess.check_output(
    ["git", "rev-parse", "HEAD"],
    cwd=root,
    text=True,
).strip()

if marker.exists():
    saved = json.loads(marker.read_text())
    if saved.get("benchmark_commit") != commit:
        raise RuntimeError("Asset preparation marker has another commit.")
    print("[OK] Assets were already prepared for this runtime.")
else:
    subprocess.run(["setup-env"], cwd=root, check=True)
    marker.write_text(
        json.dumps({"benchmark_commit": commit}, indent=2) + "\\n"
    )
    print("[OK] Official asset preparation completed.")
"""

    subprocess.run(
        [
            "docker", "run", "--rm",
            "--platform", PLATFORM,
            "--mount",
            f"type=volume,source={volume},target=/opt/tua-bench",
            "--mount",
            "type=bind,source=/var/run/docker.sock,"
            "target=/var/run/docker.sock",
            IMAGE,
            "python", "-c", prepare_code,
        ],
        cwd=ROOT,
        check=True,
    )

    evidence_dir = ROOT / ".cache" / "runtime"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    info = {
        "image": IMAGE,
        "image_id": image_id,
        "platform": PLATFORM,
        "benchmark_commit": commit,
        "asset_volume": volume,
    }

    info_path = evidence_dir / "asset_info.json"
    info_path.write_text(
        json.dumps(info, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print("[OK] Prepared assets preserved in Docker storage.")
    print(f"[OK] Local storage information saved: {info_path}")
    print("No model API calls or graded benchmark attempts were launched.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        print("[FAIL] Asset preparation command failed.", file=sys.stderr)
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