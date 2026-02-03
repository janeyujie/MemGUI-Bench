# MemGUI-Bench

A memory-centric benchmark for evaluating Mobile GUI Agents in dynamic environments.

**[Paper](https://arxiv.org/) | [Website](https://lgy0404.github.io/MemGUI-Bench/) | [Leaderboard](https://lgy0404.github.io/MemGUI-Bench/leaderboard.html)**

---

## Environment Setup

### Option 1: Docker (Recommended)

Use our pre-configured Docker image with all dependencies installed:

```bash
# Pull the image
docker pull memguibench/memgui-bench:latest

# Run container with GPU support
docker run -it --gpus all \
  -v $(pwd)/results:/workspace/results \
  -p 5555:5555 \
  memguibench/memgui-bench:latest

# Inside container
cd /workspace/MemGUI-Bench
python run.py
```

The Docker image includes:

- Pre-configured Android emulator with MemGUI-AVD
- All required conda environments
- ADB and Android SDK tools

### Option 2: Local Setup

For developers who prefer local installation:

#### Prerequisites

1. **Conda**: Install from [conda.io](https://conda.io/projects/conda/en/latest/user-guide/install/index.html)
2. **Android Debug Bridge (ADB)**: Install from [Android Developer](https://developer.android.com/tools/adb) and add to PATH
3. **Android Studio & AVD**:

   - Download and install [Android Studio](https://developer.android.com/studio)
   - Download the pre-configured MemGUI-AVD emulator snapshot:
     - **Download**: [Baidu Netdisk](https://pan.baidu.com/s/11MhISCYTV5JJPjf9FALy2g?pwd=tfnb) (Code: `tfnb`)
     - **File**: `MemGUI-AVD-250704-base.zip`
   - Extract to your AVD directory:
     - **Windows**: `C:\Users\[Username]\.android\avd\`
     - **macOS**: `~/Library/Android/avd/`
     - **Linux**: `~/.android/avd/`
   - Launch Android Studio → Device Manager → Start MemGUI-AVD

#### Repository Setup

```bash
# Clone repository with submodules
git clone --recursive https://github.com/lgy0404/MemGUI-Bench.git
cd MemGUI-Bench

# If already cloned without --recursive, init submodules manually:
# git submodule update --init --recursive

# Run setup script
./setup.sh

# Configure
cp config.yaml.example.opensource config.yaml
# Edit config.yaml with your paths
```

---

## Configuration

Edit `config.yaml` to match your environment:

```yaml
# Part 1: Environment Mode
ENVIRONMENT_MODE: "local"  # "local" or "docker"

# Part 2: Experiment Settings
AGENT_NAME: "Qwen3VL"
DATASET_PATH: "./data/memgui-tasks-all.csv"
SESSION_ID_SUFFIX: "my-experiment"

# Part 3: API & Parallelism
BASE_URL: "https://api.openai.com/v1"
NUM_OF_EMULATOR: 4
MAX_EVAL_SUBPROCESS: 8

# Part 4: Model API Keys
QWEN_API_KEY: "your-api-key"
QWEN_MODEL: "qwen3-vl-8b"

# Part 5: Paths (for local mode)
_MODE_PRESETS:
  environment:
    local:
      _CONDA_PATH: "/path/to/miniconda3"
      _EMULATOR_PATH: "/path/to/android-sdk/emulator/emulator"
      _ANDROID_SDK_PATH: "/path/to/android-sdk"
      _SYS_AVD_HOME: "/path/to/.android/avd"
      _SOURCE_AVD_HOME: "/path/to/.android/avd"
```

---

## Usage

### Running the Benchmark

```bash
conda activate android_world
python run.py
```

### Command-line Arguments

| Argument            | Default  | Description                                |
| ------------------- | -------- | ------------------------------------------ |
| `--agents`        | config   | Agent name(s), comma-separated             |
| `--mode`          | `full` | `full` (exec+eval) / `exec` / `eval` |
| `--session_id`    | config   | Session identifier for results             |
| `--task_id`       | None     | Run specific task only                     |
| `--max_attempts`  | 3        | Max attempts per task                      |
| `--overwrite`     | False    | Overwrite existing results                 |
| `--no_concurrent` | False    | Disable parallel evaluation                |

### Examples

```bash
# Full benchmark (execution + evaluation)
python run.py

# Run specific task
python run.py --task_id 001-FindProductAndFilter

# Evaluation only (on existing trajectories)
python run.py --mode eval --session_id my-experiment

# Multiple attempts
python run.py --max_attempts 5

# Disable parallel execution
python run.py --no_concurrent
```

---

## Benchmark Session

Each `session_id` creates an isolated benchmark folder in `./results/`.

- The dataset is copied to `results.csv` to track progress
- Re-running the same session resumes from incomplete tasks
- Results accumulate across runs

### Output Structure

```
results/session-{session_id}/
├── results.csv                    # Aggregated execution & evaluation metrics
├── results.csv.lock               # File lock for concurrent access
├── metrics_summary.json           # Computed benchmark metrics
├── {agent_name}.json              # Leaderboard format (for submission)
├── config.yaml                    # Config snapshot for reproducibility
│
└── {task_id}/
    └── {agent_name}/
        └── attempt_{n}/
            ├── log.json                    # Execution log with actions
            ├── 0.png, 1.png, ...          # Raw screenshots per step
            ├── stdout.txt, stderr.txt     # Process output logs
            ├── error.json                 # Error info (if any)
            │
            ├── visualize_actions/         # Action visualization images
            │   └── step_1.png, step_2.png, ...
            │
            ├── single_actions/            # Individual action screenshots
            │   └── step_1.png, step_2.png, ...
            │
            ├── puzzle/                    # Evaluation puzzle images
            │   ├── puzzle.png
            │   ├── pre_eval_puzzle.png
            │   └── supplemental_puzzle.png (if needed)
            │
            ├── evaluation_summary.json    # Detailed evaluation results
            ├── final_decision.json        # Final evaluation decision
            ├── irr_analysis.json          # IRR evaluation results
            ├── badcase_analysis.json      # BadCase classification
            └── step_*_description.json    # Step-by-step analysis
```

---

## Metrics

The benchmark automatically computes:

| Metric               | Description                                  |
| -------------------- | -------------------------------------------- |
| **Pass@K**     | Success rate within K attempts               |
| **IRR**        | Information Retrieval Rate (memory accuracy) |
| **FRR**        | Failure Recovery Rate (learning from errors) |
| **MTPR**       | Memory Task Performance Ratio                |
| **Step Ratio** | Agent steps / Golden steps                   |
| **Time/Step**  | Average execution time per step              |
| **Cost/Step**  | API cost per step (if applicable)            |

Results are saved to `metrics_summary.json` and `{agent_name}.json` (leaderboard format).

---

## Adding a New Agent

### Step 1: Add Config

Add your agent to `config.yaml`:

```yaml
AGENTS:
  - NAME: "MyAgent"
    REPO_PATH: "./framework/models/MyAgent"
    ENV_NAME: "my_agent_env"
```

### Step 2: Implement Agent Class

Create your agent class in `framework/agents.py`:

```python
class MyAgent(AndroidWorldAgent):
    agent_name = "MyAgent"
  
    def construct_command(self, task, full_task_description, output_dir, device):
        script = "run.py"
        args = f'--task "{full_task_description}" --output {output_dir} --device {device["serial"]}'
        return script, args
```

### Step 3: Output Format

Your agent must output:

- Screenshots: `0.png`, `1.png`, ... (one per step)
- Log file: `log.json` with execution summary

The benchmark handles evaluation automatically.

---

## Leaderboard Submission

After running the benchmark:

### 1. Submit Results JSON (Required)

Find `{agent_name}.json` in your session folder and fill in metadata:

```json
{
  "name": "YourAgent",
  "backbone": "GPT-4V",           // or "-" for fine-tuned models
  "type": "Agentic Workflow",     // or "Agent-as-a-Model"
  "institution": "Your Institution",
  "date": "2026-02-03",
  "paperLink": "https://arxiv.org/...",
  "codeLink": "https://github.com/...",
  "hasUITree": true,
  "hasLongTermMemory": false,
  // ... auto-generated metrics below (do not modify)
}
```

Submit via Pull Request to [lgy0404/MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench) → `docs/data/agents/`

### 2. Upload Trajectories (Optional but Recommended)

Compress and submit via PR to [lgy0404/memgui-bench-trajs](https://huggingface.co/datasets/lgy0404/memgui-bench-trajs):

```bash
# Compress session folder (filename should match your agent JSON, e.g., mobile-agent-v2.zip)
cd results && zip -r your-agent-name.zip session-{id}

# Upload via HuggingFace Web UI:
# 1. Go to https://huggingface.co/datasets/lgy0404/memgui-bench-trajs
# 2. Click "Community" → "New Pull Request" → "Upload files"
# 3. Upload your zip file and submit the PR
```

See [submission guide](https://lgy0404.github.io/MemGUI-Bench/submission.html) for details.

---

## Dataset

| File                     | Tasks | Description              |
| ------------------------ | ----- | ------------------------ |
| `memgui-tasks-all.csv` | 128   | Full benchmark           |
| `memgui-tasks-40.csv`  | 40    | Subset for quick testing |
| `memgui-debug-6.csv`   | 6     | Debug set                |

Task fields: `task_identifier`, `task_description`, `task_app`, `num_apps`, `requires_ui_memory`, `task_difficulty`, `golden_steps`

---

## Citation

```bibtex
@article{memguibench2026,
  title={MemGUI-Bench: Benchmarking Memory of Mobile GUI Agents},
  author={Liu, Guangyi and Zhao, Pengxiang and Liang, Yaozhen and others},
  journal={arXiv preprint},
  year={2026}
}
```

## License

[MIT License](LICENSE)
