# PE6203 — Team setup guide (Windows and macOS)

Run one TUA-Bench task using the default Terminus-2 harness and save one results JSON. This guide matches the project at the completed nuclei smoke test: **it does not assume the later 40-task batch runner or custom harness has been added.**

**Before sharing:** replace `YOUR_TEAM_REPO_URL` below with the HTTPS clone URL from GitHub → **Code → HTTPS**. Commit the scripts, Dockerfile, configurations, and shared manifests, including the runtime permission fix used in the successful graded run.

## 1. Install the tools

| Tool | Windows | macOS |
| --- | --- | --- |
| VS Code | [Download VS Code](https://code.visualstudio.com/download) | Same link; choose your Mac build |
| Python | [Install Python 3.11 or newer](https://www.python.org/downloads/); enable **Add Python to PATH** if offered | Install Python 3.11 or newer from the same website |
| Git | [Install Git for Windows](https://git-scm.com/downloads/win); default options are sufficient | Open Terminal and run `git --version`; accept the Command Line Tools installation prompt if shown, then retry |
| Docker Desktop | Follow the Windows instructions below | Follow the Mac instructions below |

The host uses Python 3.11 or newer to launch our scripts. The Docker runtime uses its own Python 3.12 and benchmark dependencies. You do not need to install Harbor or CellProfiler on your laptop.

Allow substantial free disk space for images and downloaded assets. A machine with 16 GB RAM is a practical starting point for this task; its declared container limit is 8 GB RAM and 6 CPUs. Close memory-heavy apps during a run. Actual storage and performance depend on the task.

### Windows: install Docker Desktop

1. Use a supported Windows version and check the [official requirements and installer](https://docs.docker.com/desktop/setup/install/windows-install/). For a typical Intel/AMD laptop, download the **x86_64** installer.
2. Install Docker Desktop, selecting the **WSL 2** backend if asked. Restart Windows if requested.
3. If Docker reports that WSL is missing, open **PowerShell as administrator** and run these commands separately:

   ```powershell
   wsl --install --no-distribution
   wsl --update
   ```

   Restart Windows. If virtualization is disabled, enable it in your computer's BIOS/UEFI using the manufacturer's instructions.
4. Open Docker Desktop, complete its setup, and wait for the engine to start. Use **Linux containers**. If its menu offers “Switch to Linux containers”, select it.
5. Keep Docker Desktop running while using the project.

You can work entirely in Windows VS Code and PowerShell. WSL provides Docker's background runtime; a separate Ubuntu installation and Ubuntu terminal are not needed for this workflow.

### macOS: install Docker Desktop

1. Open **Apple menu → About This Mac**. Note whether it lists an Apple chip or an Intel processor.
2. Download the matching **Apple silicon** or **Intel** installer from the [official Mac installation page](https://docs.docker.com/desktop/setup/install/mac-install/).
3. Open the `.dmg`, drag Docker into **Applications**, and launch Docker Desktop. Complete setup and wait for the engine to start.
4. In **Docker Desktop → Settings → Advanced**, enable **Allow the default Docker socket to be used** (wording may vary). This project mounts `/var/run/docker.sock` so Harbor can launch task containers. Apply changes and restart Docker if requested.
5. Keep Docker Desktop running. For Apple Silicon, retain the team's `linux/amd64` runtime platform; emulation may be slower. If Docker offers an x86/amd64 emulation or Rosetta setting, follow its guidance for the selected virtualization backend.

**Compatibility status:** the nuclei run has been verified on Windows with a Linux amd64 engine. Mac users must pass the runtime checks below before launching a paid attempt; Apple Silicon execution has not yet been verified by the team.

## 2. Check the installations

After installing the tools, close and reopen VS Code so it picks up PATH changes. Open **Terminal → New Terminal**. Use **PowerShell** on Windows and the normal **zsh/bash** terminal on Mac.

Run each line separately:

```text
git --version
docker version
docker compose version
docker run --rm hello-world
```

`docker version` should show both **Client** and **Server**, and `hello-world` should print “Hello from Docker!”.

Check Python:

| Windows | Mac |
| --- | --- |
| `python --version` | `python3 --version` |

If Windows does not recognize `python`, try `py -3 --version`. If that works, use `py -3` instead of `python` throughout this guide.

## 3. Clone and open the repository

In VS Code, select **View → Command Palette → Git: Clone**, paste `YOUR_TEAM_REPO_URL`, choose a local folder, and click **Open** when cloning finishes. Sign into GitHub if the repository is private.

Alternatively, run:

```text
git clone YOUR_TEAM_REPO_URL
cd Cost-Aware-Harness-Optimization-Project
```

Then select **File → Open Folder** and open that project folder in VS Code. Prefer an ordinary local folder rather than OneDrive/iCloud storage.

Open **Terminal → New Terminal**. The current folder must contain `runner.py`, `scripts/`, `configs/`, and `manifests/`. Run all remaining commands from this project root, not from inside `scripts/`.

## 4. Download the benchmark and verify the fixed subset

Run in this order, choosing your OS column:

| Action | Windows | Mac |
| --- | --- | --- |
| Download the pinned benchmark | `python runner.py setup` | `python3 runner.py setup` |
| Check tools and task selection | `python runner.py check` | `python3 runner.py check` |

The shared manifests define the exact benchmark revision and the team's **40 evaluation tasks plus 5 development tasks**. Setup should restore the benchmark locally; do not select a new random subset.

Expected checks include 120 available benchmark tasks, 40 unique evaluation IDs, 5 unique development IDs, and no overlap. If a shared manifest is missing, retrieve it from the team repository before proceeding.

## 5. Build and verify the container runtime

| Windows | Mac |
| --- | --- |
| `python scripts/build_runtime.py` | `python3 scripts/build_runtime.py` |

The first invocation builds the runtime. The team's updated script checks an existing runtime on subsequent invocations. Wait for all runtime checks to pass, including access to Docker and launching a separate test container.

The initial build can take time. Leave Docker Desktop running and your internet connection active.

## 6. Prepare benchmark assets

| Windows | Mac |
| --- | --- |
| `python scripts/prepare_assets.py` | `python3 scripts/prepare_assets.py` |

This downloads the official external input/reference assets into Docker storage and writes local asset information. It does not call the model. Wait for the asset preparation success message.

Each teammate performs setup, build, and asset preparation on their own machine. Git cloning does not transfer Docker images, volumes, or `.cache` information. Do not copy another teammate's `.cache/runtime` files.

## 7. Add your API key

In VS Code, create a file named **`.env`** in the project root. If `.env.example` exists, copy it and rename the copy to `.env`.

Add:

```dotenv
OPENROUTER_API_KEY=your_actual_key_here
```

Obtain an authorized key from the team lead or create one through [OpenRouter](https://openrouter.ai/). Model access requires available credits. Keep `.env` excluded by `.gitignore`; never paste the key into code, GitHub, screenshots, or results you share.

Open `configs/baseline.json` and confirm the agreed smoke-test settings:

```json
{
  "agent": "terminus-2",
  "model": "openrouter/qwen/qwen3-coder",
  "task": "000-count-nuclei",
  "attempts": 1,
  "concurrency": 1,
  "trial_retries": 0
}
```

These are the required core fields; preserve any existing configuration ID, phase, repeat, variant, and component metadata. Do not overwrite the whole file just to match this shortened example.

## 8. Run a free preflight, then one paid task

First run:

| Windows | Mac |
| --- | --- |
| `python scripts/run_tasks.py --check-only` | `python3 scripts/run_tasks.py --check-only` |

This validates the prepared task, benchmark revision, container access, and Harbor command options. It does **not** validate API credits/model availability or prove the task will pass.

Once the preflight passes, launch **one paid model attempt**:

| Windows | Mac |
| --- | --- |
| `python scripts/run_tasks.py` | `python3 scripts/run_tasks.py` |

Coordinate with the team before running paid attempts to avoid duplicate spending. Keep the laptop awake and Docker running. The first task image build can take several minutes with little terminal output. Do not launch another copy merely because the terminal is quiet.

## 9. Read and share the result

Open the printed `results/<run_id>/result.json` in VS Code.

| Field | Meaning |
| --- | --- |
| `status: graded` | The official verifier produced a usable reward |
| `official_reward: 1` | This task passed |
| `official_reward: 0` | This task failed its grading checks; the run can still be valid |
| `verification_error` or `execution_error` | Investigate before another paid attempt; this is not a graded zero |
| `usage.reported_total_cost_usd` | Cost reported by Harbor for the attempt |
| `timing.trial_seconds` | Recorded trial duration |
| `null` measurements | Unknown/unavailable, not zero |

The JSON also embeds text logs and trajectories for failure analysis. The printed OpenRouter key allowance is key-level information, not the account's total credit balance.

Share the JSON and run ID with the team. For the initial successful grading smoke test, the model produced **7**, the reference was **6**, and the official reward was **0**. Your fresh attempt may differ.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `python` not found on Windows | Try `py -3`; reopen VS Code after installing Python |
| Docker connection error or no Server section | Start Docker Desktop and wait for the engine |
| Windows shows a Windows-container engine | Switch Docker Desktop to Linux containers |
| Mac reports a missing Docker socket | Enable the default socket in Docker Desktop → Settings → Advanced |
| `exec format error` / architecture warning | Check that runtime and task containers use the team's platform; do not change the platform independently |
| Missing manifests or scripts | Check that the latest team code is committed/pushed, then pull it |
| Missing assets / local runtime metadata | Run setup, build, and prepare-assets on this machine |
| `RewardFileNotFoundError` | Confirm the checked-in runner contains the proven `os.umask(0)` launcher fix; share the JSON and inspect permissions before paying for a retry |
| Only repeated “Provider List” messages | These alone do not diagnose failure; inspect the final status and embedded logs |
| Out of memory / no disk space | Review Docker resources and free disk space; retain result files while troubleshooting |

For later sessions: start Docker Desktop, reopen the project, and use `git pull` after checking your working tree for uncommitted changes. Repeat runtime/asset preparation if the team's runtime or benchmark revision changes.
