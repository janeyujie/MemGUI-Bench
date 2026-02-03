"""
Real-time progress monitoring and metrics calculation module.
Provides functions to calculate and display Pass@K, IRR, FRR, MTPR metrics.
Also handles saving metrics to files for persistence and analysis.
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional


# File names for metrics storage
REALTIME_METRICS_FILE = "realtime_metrics.json"
METRICS_HISTORY_FILE = "realtime_metrics_history.jsonl"
FINAL_SUMMARY_FILE = "final_metrics_summary.md"
PROGRESS_TIMING_FILE = "progress_timing.json"

# Global timing data
_start_time = None
_task_timing_data = {}


def initialize_timing(output_dir: str) -> None:
    """
    Initialize timing data for progress tracking.

    Args:
        output_dir: Base output directory for saving timing data
    """
    global _start_time, _task_timing_data
    _start_time = datetime.now()
    _task_timing_data = {}

    # Save initial timing
    timing_path = os.path.join(output_dir, PROGRESS_TIMING_FILE)
    try:
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump(
                {"start_time": _start_time.isoformat(), "task_timings": {}}, f, indent=2
            )
    except IOError:
        pass


def record_task_completion(task_id: str, stage: str, output_dir: str) -> None:
    """
    Record completion time for a task stage.

    Args:
        task_id: Task identifier
        stage: Stage name ('execution' or 'evaluation')
        output_dir: Base output directory
    """
    global _task_timing_data

    if task_id not in _task_timing_data:
        _task_timing_data[task_id] = {}

    _task_timing_data[task_id][stage] = datetime.now().isoformat()

    # Save updated timing
    timing_path = os.path.join(output_dir, PROGRESS_TIMING_FILE)
    try:
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "start_time": _start_time.isoformat() if _start_time else None,
                    "task_timings": _task_timing_data,
                },
                f,
                indent=2,
            )
    except IOError:
        pass


def calculate_time_estimates(
    total_tasks: int, evaluated_count: int, start_time: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Calculate time estimates based on progress.

    Args:
        total_tasks: Total number of tasks
        evaluated_count: Number of evaluated tasks
        start_time: Start time of the run

    Returns:
        Dictionary with timing information
    """
    if start_time is None:
        start_time = _start_time

    if start_time is None:
        return {
            "elapsed": "N/A",
            "estimated_remaining": "N/A",
            "estimated_total": "N/A",
            "eta": "N/A",
        }

    now = datetime.now()
    elapsed = now - start_time
    elapsed_str = str(elapsed).split(".")[0]  # Remove microseconds

    if evaluated_count == 0:
        return {
            "elapsed": elapsed_str,
            "estimated_remaining": "N/A",
            "estimated_total": "N/A",
            "eta": "N/A",
        }

    # Calculate average time per task
    avg_time_per_task = elapsed / evaluated_count
    remaining_tasks = total_tasks - evaluated_count
    estimated_remaining_time = avg_time_per_task * remaining_tasks
    estimated_total_time = avg_time_per_task * total_tasks
    eta = now + estimated_remaining_time

    return {
        "elapsed": elapsed_str,
        "estimated_remaining": str(estimated_remaining_time).split(".")[0],
        "estimated_total": str(estimated_total_time).split(".")[0],
        "eta": eta.strftime("%Y-%m-%d %H:%M:%S"),
    }


def collect_task_results(
    task_scope: List[Any],
    agent_scope: List[str],
    output_dir: str,
    max_attempts: int,
    only_evaluated: bool = False,
) -> Dict[str, Any]:
    """
    Collect execution and evaluation results for all tasks.

    Args:
        task_scope: List of task namedtuples with task_identifier and requires_ui_memory
        agent_scope: List of agent names
        output_dir: Base output directory
        max_attempts: Maximum number of attempts per task
        only_evaluated: If True, only include evaluated tasks in statistics

    Returns:
        Dictionary containing collected metrics data
    """
    # Classify tasks
    memory_tasks = [
        t for t in task_scope if getattr(t, "requires_ui_memory", "N") == "Y"
    ]
    standard_tasks = [
        t for t in task_scope if getattr(t, "requires_ui_memory", "N") != "Y"
    ]

    # First pass: identify evaluated tasks if only_evaluated is True
    evaluated_task_ids = set()
    if only_evaluated:
        for agent_name in agent_scope:
            for task in task_scope:
                task_id = task.task_identifier
                for attempt in range(1, max_attempts + 1):
                    attempt_dir = os.path.join(
                        output_dir, task_id, agent_name, f"attempt_{attempt}"
                    )
                    eval_path = os.path.join(attempt_dir, "evaluation_summary.json")
                    if os.path.exists(eval_path):
                        evaluated_task_ids.add(task_id)
                        break

    # Filter tasks if only_evaluated
    if only_evaluated:
        task_scope_filtered = [
            t for t in task_scope if t.task_identifier in evaluated_task_ids
        ]
        memory_tasks_filtered = [
            t for t in memory_tasks if t.task_identifier in evaluated_task_ids
        ]
        standard_tasks_filtered = [
            t for t in standard_tasks if t.task_identifier in evaluated_task_ids
        ]
    else:
        task_scope_filtered = task_scope
        memory_tasks_filtered = memory_tasks
        standard_tasks_filtered = standard_tasks

    total_tasks = len(task_scope_filtered)
    memory_tasks_total = len(memory_tasks_filtered)
    standard_tasks_total = len(standard_tasks_filtered)

    executed_count = 0
    evaluated_count = 0
    irr_sum = 0.0
    irr_count = 0

    # Pass@K tracking (all, memory, standard)
    pass_at_k_all = {k: set() for k in range(1, max_attempts + 1)}
    pass_at_k_memory = {k: set() for k in range(1, max_attempts + 1)}
    pass_at_k_standard = {k: set() for k in range(1, max_attempts + 1)}

    # Track attempt results for FRR calculation
    task_attempt_results = {}

    for agent_name in agent_scope:
        for task in task_scope_filtered:
            task_id = task.task_identifier
            is_memory_task = getattr(task, "requires_ui_memory", "N") == "Y"
            first_success_attempt = None
            attempt_results = {}
            
            # Track completion for ALL attempts
            execution_count = 0
            evaluation_count = 0

            for attempt in range(1, max_attempts + 1):
                attempt_dir = os.path.join(
                    output_dir, task_id, agent_name, f"attempt_{attempt}"
                )
                log_path = os.path.join(attempt_dir, "log.json")
                eval_path = os.path.join(attempt_dir, "evaluation_summary.json")
                irr_path = os.path.join(attempt_dir, "irr_analysis.json")

                if os.path.exists(log_path):
                    execution_count += 1

                if os.path.exists(eval_path):
                    evaluation_count += 1
                    try:
                        with open(eval_path, "r") as f:
                            result = json.load(f).get("final_result", 0)
                            attempt_results[attempt] = result == 1
                            if result == 1 and first_success_attempt is None:
                                first_success_attempt = attempt
                    except (json.JSONDecodeError, IOError):
                        attempt_results[attempt] = False

                # Read IRR results (only for memory tasks, attempt 1)
                if is_memory_task and attempt == 1 and os.path.exists(irr_path):
                    try:
                        with open(irr_path, "r") as f:
                            irr_data = json.load(f)
                            irr_pct = irr_data.get("irr_percentage")
                            if irr_pct is not None and isinstance(
                                irr_pct, (int, float)
                            ):
                                irr_sum += irr_pct
                                irr_count += 1
                    except (json.JSONDecodeError, IOError):
                        pass

            task_attempt_results[task_id] = attempt_results

            # Task is considered executed/evaluated ONLY when ALL attempts are done
            if execution_count == max_attempts:
                executed_count += 1
            if evaluation_count == max_attempts:
                evaluated_count += 1

            # Pass@K calculation
            if first_success_attempt is not None:
                for k in range(first_success_attempt, max_attempts + 1):
                    pass_at_k_all[k].add(task_id)
                    if is_memory_task:
                        pass_at_k_memory[k].add(task_id)
                    else:
                        pass_at_k_standard[k].add(task_id)

    return {
        "total_tasks": total_tasks,
        "memory_tasks_total": memory_tasks_total,
        "standard_tasks_total": standard_tasks_total,
        "executed_count": executed_count,
        "evaluated_count": evaluated_count,
        "irr_sum": irr_sum,
        "irr_count": irr_count,
        "pass_at_k_all": pass_at_k_all,
        "pass_at_k_memory": pass_at_k_memory,
        "pass_at_k_standard": pass_at_k_standard,
        "task_attempt_results": task_attempt_results,
        "max_attempts": max_attempts,
    }


def calculate_frr(
    task_attempt_results: Dict[str, Dict[int, bool]], max_attempts: int
) -> Tuple[float, Dict[int, int], int]:
    """
    Calculate Failure Recovery Rate (FRR).

    FRR = ((w_2 * R_2) + (w_3 * R_3) + ... + (w_n * R_n)) / N_failed_1 * 100

    Where:
    - R_k: Number of tasks that failed on attempts 1 to k-1 but succeeded on attempt k
    - w_k: Weight for recovery at attempt k (decreases as k increases)
    - N_failed_1: Number of tasks that failed on attempt 1

    Args:
        task_attempt_results: Dict mapping task_id to {attempt_num: success_bool}
        max_attempts: Maximum number of attempts

    Returns:
        Tuple of (frr, recovery_counts_dict, n_failed_1)
    """
    # Weight decreases for later recoveries: w_2=1.0, w_3=0.5, w_4=0.25, ...
    weights = {k: 1.0 / (2 ** (k - 2)) for k in range(2, max_attempts + 1)}

    n_failed_1 = 0
    recovery_counts = {k: 0 for k in range(2, max_attempts + 1)}

    for task_id, results in task_attempt_results.items():
        att_1 = results.get(1, False)

        if not att_1:  # Failed on attempt 1
            n_failed_1 += 1
            # Check which attempt recovered (if any)
            all_prev_failed = True
            for k in range(2, max_attempts + 1):
                if results.get(k, False) and all_prev_failed:
                    recovery_counts[k] += 1
                    break
                if results.get(k, False):
                    all_prev_failed = False
                    break
                # If attempt k also failed, continue checking

    # Calculate weighted FRR
    weighted_sum = sum(
        weights[k] * recovery_counts[k] for k in range(2, max_attempts + 1)
    )
    frr = (weighted_sum / n_failed_1 * 100) if n_failed_1 > 0 else 0

    return frr, recovery_counts, n_failed_1


def calculate_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate all metrics from collected data.

    Args:
        data: Dictionary from collect_task_results()

    Returns:
        Dictionary containing all calculated metrics
    """
    total_tasks = data["total_tasks"]
    memory_tasks_total = data["memory_tasks_total"]
    standard_tasks_total = data["standard_tasks_total"]
    max_attempts = data["max_attempts"]

    # IRR
    avg_irr = data["irr_sum"] / data["irr_count"] if data["irr_count"] > 0 else 0

    # FRR
    frr, recovery_counts, n_failed_1 = calculate_frr(
        data["task_attempt_results"], max_attempts
    )

    # MTPR (Memory Task Performance Ratio) = SR_memory@1 / SR_standard@1
    sr_memory_1 = (
        len(data["pass_at_k_memory"][1]) / memory_tasks_total * 100
        if memory_tasks_total > 0
        else 0
    )
    sr_standard_1 = (
        len(data["pass_at_k_standard"][1]) / standard_tasks_total * 100
        if standard_tasks_total > 0
        else 0
    )
    mtpr = (sr_memory_1 / sr_standard_1) if sr_standard_1 > 0 else 0

    # Pass@K rates
    pass_at_k_rates = {}
    pass_at_k_memory_rates = {}
    pass_at_k_standard_rates = {}

    for k in range(1, max_attempts + 1):
        pass_at_k_rates[k] = (
            len(data["pass_at_k_all"][k]) / total_tasks * 100 if total_tasks > 0 else 0
        )
        pass_at_k_memory_rates[k] = (
            len(data["pass_at_k_memory"][k]) / memory_tasks_total * 100
            if memory_tasks_total > 0
            else 0
        )
        pass_at_k_standard_rates[k] = (
            len(data["pass_at_k_standard"][k]) / standard_tasks_total * 100
            if standard_tasks_total > 0
            else 0
        )

    return {
        "avg_irr": avg_irr,
        "irr_count": data["irr_count"],
        "frr": frr,
        "recovery_counts": recovery_counts,
        "n_failed_1": n_failed_1,
        "mtpr": mtpr,
        "sr_memory_1": sr_memory_1,
        "sr_standard_1": sr_standard_1,
        "pass_at_k_rates": pass_at_k_rates,
        "pass_at_k_memory_rates": pass_at_k_memory_rates,
        "pass_at_k_standard_rates": pass_at_k_standard_rates,
    }


def build_metrics_snapshot(
    data: Dict[str, Any], metrics: Dict[str, Any], trigger: str
) -> Dict[str, Any]:
    """
    Build a complete metrics snapshot for saving.

    Args:
        data: Raw collected data
        metrics: Calculated metrics
        trigger: What triggered this snapshot

    Returns:
        Complete metrics snapshot dictionary
    """
    max_attempts = data["max_attempts"]

    # Convert sets to counts for JSON serialization
    pass_at_k_counts = {
        k: len(data["pass_at_k_all"][k]) for k in range(1, max_attempts + 1)
    }
    pass_at_k_memory_counts = {
        k: len(data["pass_at_k_memory"][k]) for k in range(1, max_attempts + 1)
    }
    pass_at_k_standard_counts = {
        k: len(data["pass_at_k_standard"][k]) for k in range(1, max_attempts + 1)
    }

    return {
        "timestamp": datetime.now().isoformat(),
        "trigger": trigger,
        "progress": {
            "total_tasks": data["total_tasks"],
            "memory_tasks": data["memory_tasks_total"],
            "standard_tasks": data["standard_tasks_total"],
            "executed": data["executed_count"],
            "evaluated": data["evaluated_count"],
            "execution_rate": (
                data["executed_count"] / data["total_tasks"] * 100
                if data["total_tasks"] > 0
                else 0
            ),
            "evaluation_rate": (
                data["evaluated_count"] / data["total_tasks"] * 100
                if data["total_tasks"] > 0
                else 0
            ),
        },
        "pass_at_k": {
            "all": {
                "counts": pass_at_k_counts,
                "rates": metrics["pass_at_k_rates"],
            },
            "memory": {
                "counts": pass_at_k_memory_counts,
                "rates": metrics["pass_at_k_memory_rates"],
            },
            "standard": {
                "counts": pass_at_k_standard_counts,
                "rates": metrics["pass_at_k_standard_rates"],
            },
        },
        "core_metrics": {
            "irr": {
                "average": metrics["avg_irr"],
                "evaluated_count": metrics["irr_count"],
                "total_memory_tasks": data["memory_tasks_total"],
            },
            "frr": {
                "rate": metrics["frr"],
                "recovery_counts": metrics["recovery_counts"],
                "first_attempt_failures": metrics["n_failed_1"],
            },
            "mtpr": {
                "ratio": metrics["mtpr"],
                "memory_sr_at_1": metrics["sr_memory_1"],
                "standard_sr_at_1": metrics["sr_standard_1"],
            },
        },
        "max_attempts": max_attempts,
    }


def save_realtime_metrics(output_dir: str, snapshot: Dict[str, Any]) -> None:
    """
    Save current metrics snapshot to realtime_metrics.json.

    Args:
        output_dir: Base output directory
        snapshot: Metrics snapshot to save
    """
    metrics_path = os.path.join(output_dir, REALTIME_METRICS_FILE)
    try:
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"Warning: Failed to save realtime metrics: {e}")


def append_metrics_history(output_dir: str, snapshot: Dict[str, Any]) -> None:
    """
    Append metrics snapshot to history file (JSONL format).

    Args:
        output_dir: Base output directory
        snapshot: Metrics snapshot to append
    """
    history_path = os.path.join(output_dir, METRICS_HISTORY_FILE)
    try:
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except IOError as e:
        print(f"Warning: Failed to append metrics history: {e}")


def generate_final_summary(output_dir: str, snapshot: Dict[str, Any]) -> None:
    """
    Generate final metrics summary in Markdown format.

    Args:
        output_dir: Base output directory
        snapshot: Final metrics snapshot
    """
    summary_path = os.path.join(output_dir, FINAL_SUMMARY_FILE)

    progress = snapshot["progress"]
    pass_at_k = snapshot["pass_at_k"]
    core = snapshot["core_metrics"]
    max_attempts = snapshot["max_attempts"]

    md_content = f"""# Evaluation Metrics Summary

Generated: {snapshot["timestamp"]}

## Progress Overview

| Metric | Value |
|--------|-------|
| Total Tasks | {progress["total_tasks"]} |
| Memory Tasks | {progress["memory_tasks"]} |
| Standard Tasks | {progress["standard_tasks"]} |
| Executed | {progress["executed"]} ({progress["execution_rate"]:.1f}%) |
| Evaluated | {progress["evaluated"]} ({progress["evaluation_rate"]:.1f}%) |

## Pass@K Results

### Overall (All Tasks)

| K | Success Count | Success Rate |
|---|---------------|--------------|
"""

    for k in range(1, max_attempts + 1):
        md_content += f"| {k} | {pass_at_k['all']['counts'][k]} | {pass_at_k['all']['rates'][k]:.1f}% |\n"

    md_content += """
### Memory Tasks

| K | Success Count | Success Rate |
|---|---------------|--------------|
"""

    for k in range(1, max_attempts + 1):
        md_content += f"| {k} | {pass_at_k['memory']['counts'][k]} | {pass_at_k['memory']['rates'][k]:.1f}% |\n"

    md_content += """
### Standard Tasks

| K | Success Count | Success Rate |
|---|---------------|--------------|
"""

    for k in range(1, max_attempts + 1):
        md_content += f"| {k} | {pass_at_k['standard']['counts'][k]} | {pass_at_k['standard']['rates'][k]:.1f}% |\n"

    # Recovery counts for FRR
    recovery_str = ", ".join(
        [f"R{k}={v}" for k, v in sorted(core["frr"]["recovery_counts"].items())]
    )

    md_content += f"""
## Core Metrics

| Metric | Value | Details |
|--------|-------|---------|
| IRR (Information Retention Rate) | {core["irr"]["average"]:.1f}% | {core["irr"]["evaluated_count"]}/{core["irr"]["total_memory_tasks"]} memory tasks evaluated |
| FRR (Failure Recovery Rate) | {core["frr"]["rate"]:.1f}% | {recovery_str}, First failures={core["frr"]["first_attempt_failures"]} |
| MTPR (Memory Task Performance Ratio) | {core["mtpr"]["ratio"]:.3f} | Memory@1={core["mtpr"]["memory_sr_at_1"]:.1f}%, Standard@1={core["mtpr"]["standard_sr_at_1"]:.1f}% |

## Metric Definitions

- **IRR**: Average information retention rate for memory-intensive tasks
- **FRR**: Weighted failure recovery rate (w₂=1.0, w₃=0.5, w₄=0.25, ...)
- **MTPR**: Ratio of memory task success rate to standard task success rate at Pass@1
"""

    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(md_content)
    except IOError as e:
        print(f"Warning: Failed to save final summary: {e}")


def print_realtime_progress(
    task_scope: List[Any],
    agent_scope: List[str],
    output_dir: str,
    max_attempts: int,
    trigger: str = "",
    save_to_file: bool = True,
) -> Dict[str, Any]:
    """
    Print real-time progress with comprehensive metrics and save to files.

    Displays and saves:
    - Task progress (executed/evaluated counts)
    - Time estimates (elapsed, remaining, ETA)
    - Pass@K for all tasks (two views: evaluated-only and overall)
    - IRR (Information Retention Rate) for memory tasks
    - FRR (Failure Recovery Rate)
    - MTPR (Memory Task Performance Ratio)

    Files saved:
    - realtime_metrics.json: Current metrics snapshot (overwritten each time)
    - realtime_metrics_history.jsonl: History of all snapshots (appended)
    - final_metrics_summary.md: Markdown summary (overwritten each time)

    Args:
        task_scope: List of task namedtuples
        agent_scope: List of agent names
        output_dir: Base output directory
        max_attempts: Maximum number of attempts per task
        trigger: Description of what triggered this progress print
        save_to_file: Whether to save metrics to files

    Returns:
        Metrics snapshot dictionary
    """
    # Collect results for overall (all tasks)
    data_overall = collect_task_results(
        task_scope, agent_scope, output_dir, max_attempts, only_evaluated=False
    )

    # Collect results for evaluated tasks only
    data_evaluated = collect_task_results(
        task_scope, agent_scope, output_dir, max_attempts, only_evaluated=True
    )

    # Calculate metrics for both views
    metrics_overall = calculate_metrics(data_overall)
    metrics_evaluated = calculate_metrics(data_evaluated)

    # Calculate time estimates
    time_estimates = calculate_time_estimates(
        total_tasks=len(task_scope), evaluated_count=data_overall["evaluated_count"]
    )

    # Build snapshot (use overall data for file saving)
    snapshot = build_metrics_snapshot(data_overall, metrics_overall, trigger)
    snapshot["time_estimates"] = time_estimates
    snapshot["evaluated_only_metrics"] = {
        "total_tasks": data_evaluated["total_tasks"],
        "pass_at_k": {
            "all": {
                "rates": metrics_evaluated["pass_at_k_rates"],
            },
            "memory": {
                "rates": metrics_evaluated["pass_at_k_memory_rates"],
            },
            "standard": {
                "rates": metrics_evaluated["pass_at_k_standard_rates"],
            },
        },
        "core_metrics": {
            "irr": metrics_evaluated["avg_irr"],
            "frr": metrics_evaluated["frr"],
            "mtpr": metrics_evaluated["mtpr"],
        },
    }

    # Save to files
    if save_to_file:
        save_realtime_metrics(output_dir, snapshot)
        append_metrics_history(output_dir, snapshot)
        generate_final_summary(output_dir, snapshot)

    # Extract for printing - overall data
    total_tasks_overall = len(task_scope)
    memory_tasks_total_overall = len(
        [t for t in task_scope if getattr(t, "requires_ui_memory", "N") == "Y"]
    )
    standard_tasks_total_overall = len(
        [t for t in task_scope if getattr(t, "requires_ui_memory", "N") != "Y"]
    )
    executed_count = data_overall["executed_count"]
    evaluated_count = data_overall["evaluated_count"]

    # Extract for printing - evaluated data
    total_tasks_evaluated = data_evaluated["total_tasks"]
    pass_at_k_all_eval = data_evaluated["pass_at_k_all"]
    pass_at_k_memory_eval = data_evaluated["pass_at_k_memory"]
    pass_at_k_standard_eval = data_evaluated["pass_at_k_standard"]

    # Print output
    print(f"\n{'=' * 100}")
    print(f"[*] REALTIME PROGRESS [{trigger}]")
    print(f"{'=' * 100}")

    # Progress info
    exec_pct = (
        executed_count / total_tasks_overall * 100 if total_tasks_overall > 0 else 0
    )
    eval_pct = (
        evaluated_count / total_tasks_overall * 100 if total_tasks_overall > 0 else 0
    )
    print(
        f"[>] Task Progress: Total {total_tasks_overall} tasks "
        f"(Memory: {memory_tasks_total_overall}, Standard: {standard_tasks_total_overall})"
    )
    print(
        f"    Executed: {executed_count}/{total_tasks_overall} tasks ({exec_pct:.1f}%) | "
        f"Evaluated: {evaluated_count}/{total_tasks_overall} tasks ({eval_pct:.1f}%)"
    )

    # Time estimates
    print(f"\n[>] Time Statistics:")
    print(f"    Elapsed: {time_estimates['elapsed']}")
    print(f"    Estimated Remaining: {time_estimates['estimated_remaining']}")
    print(f"    Estimated Total: {time_estimates['estimated_total']}")
    print(f"    ETA: {time_estimates['eta']}")

    # Separator for two metric views
    print(f"\n{'=' * 100}")
    print("[*] METRICS - EVALUATED TASKS ONLY")
    print(f"{'=' * 100}")

    # Evaluated tasks Pass@K
    print(f"[>] Pass@K ({total_tasks_evaluated} evaluated tasks):")
    if total_tasks_evaluated > 0:
        pass_str_eval = " | ".join(
            [
                f"@{k}: {len(pass_at_k_all_eval[k])}/{total_tasks_evaluated} ({metrics_evaluated['pass_at_k_rates'][k]:.1f}%)"
                for k in range(1, max_attempts + 1)
            ]
        )
        print(f"    Overall: {pass_str_eval}")

        if data_evaluated["memory_tasks_total"] > 0:
            mem_pass_str_eval = " | ".join(
                [
                    f"@{k}: {len(pass_at_k_memory_eval[k])}/{data_evaluated['memory_tasks_total']} ({metrics_evaluated['pass_at_k_memory_rates'][k]:.1f}%)"
                    for k in range(1, max_attempts + 1)
                ]
            )
            print(f"    Memory:  {mem_pass_str_eval}")

        if data_evaluated["standard_tasks_total"] > 0:
            std_pass_str_eval = " | ".join(
                [
                    f"@{k}: {len(pass_at_k_standard_eval[k])}/{data_evaluated['standard_tasks_total']} ({metrics_evaluated['pass_at_k_standard_rates'][k]:.1f}%)"
                    for k in range(1, max_attempts + 1)
                ]
            )
            print(f"    Standard: {std_pass_str_eval}")
    else:
        print("    N/A (no evaluated tasks yet)")

    # Evaluated Core metrics
    print(f"\n[>] Core Metrics (Evaluated):")
    if total_tasks_evaluated > 0:
        print(
            f"    IRR: {metrics_evaluated['avg_irr']:.1f}% "
            f"({metrics_evaluated['irr_count']}/{data_evaluated['memory_tasks_total']} memory tasks)"
        )

        recovery_details_eval = ", ".join(
            [
                f"R{k}={metrics_evaluated['recovery_counts'][k]}"
                for k in sorted(metrics_evaluated["recovery_counts"].keys())
            ]
        )
        print(
            f"    FRR: {metrics_evaluated['frr']:.1f}% "
            f"({recovery_details_eval}, first_failures={metrics_evaluated['n_failed_1']})"
        )

        print(
            f"    MTPR: {metrics_evaluated['mtpr']:.3f} "
            f"(Memory@1={metrics_evaluated['sr_memory_1']:.1f}%, "
            f"Standard@1={metrics_evaluated['sr_standard_1']:.1f}%)"
        )
    else:
        print("    N/A (no evaluated tasks yet)")

    # Separator for overall metrics
    print(f"\n{'=' * 100}")
    print(f"[*] METRICS - OVERALL (INCLUDING UNEVALUATED)")
    print(f"{'=' * 100}")

    # Overall Pass@K (with unevaluated tasks counted as failures)
    print(f"[>] Pass@K ({total_tasks_overall} total tasks, unevaluated=failure):")
    if total_tasks_overall > 0:
        pass_str_overall = " | ".join(
            [
                f"@{k}: {len(data_overall['pass_at_k_all'][k])}/{total_tasks_overall} ({metrics_overall['pass_at_k_rates'][k]:.1f}%)"
                for k in range(1, max_attempts + 1)
            ]
        )
        print(f"    Overall: {pass_str_overall}")

        if memory_tasks_total_overall > 0:
            mem_pass_str_overall = " | ".join(
                [
                    f"@{k}: {len(data_overall['pass_at_k_memory'][k])}/{memory_tasks_total_overall} ({metrics_overall['pass_at_k_memory_rates'][k]:.1f}%)"
                    for k in range(1, max_attempts + 1)
                ]
            )
            print(f"    Memory:  {mem_pass_str_overall}")

        if standard_tasks_total_overall > 0:
            std_pass_str_overall = " | ".join(
                [
                    f"@{k}: {len(data_overall['pass_at_k_standard'][k])}/{standard_tasks_total_overall} ({metrics_overall['pass_at_k_standard_rates'][k]:.1f}%)"
                    for k in range(1, max_attempts + 1)
                ]
            )
            print(f"    Standard: {std_pass_str_overall}")

    # Overall Core metrics
    print(f"\n[>] Core Metrics (Overall):")
    print(
        f"    IRR: {metrics_overall['avg_irr']:.1f}% "
        f"({metrics_overall['irr_count']}/{memory_tasks_total_overall} memory tasks)"
    )

    recovery_details_overall = ", ".join(
        [
            f"R{k}={metrics_overall['recovery_counts'][k]}"
            for k in sorted(metrics_overall["recovery_counts"].keys())
        ]
    )
    print(
        f"    FRR: {metrics_overall['frr']:.1f}% "
        f"({recovery_details_overall}, first_failures={metrics_overall['n_failed_1']})"
    )

    print(
        f"    MTPR: {metrics_overall['mtpr']:.3f} "
        f"(Memory@1={metrics_overall['sr_memory_1']:.1f}%, "
        f"Standard@1={metrics_overall['sr_standard_1']:.1f}%)"
    )

    print(f"{'=' * 100}\n")

    return snapshot
