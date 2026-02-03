"""
Task Allocation Module

Handles assignment of tasks to emulators with conflict avoidance strategies.
"""

from collections import defaultdict


def allocate_tasks_to_emulators(task_scope, num_devices=2):
    """
    Allocate tasks to emulators with intelligent conflict avoidance.
    
    Priority (High to Low):
    1. Avoid same task_app on same emulator (highest priority)
    2. Avoid same original_task_id on same emulator (secondary priority)
    3. Load balancing (distribute evenly across all emulators)
    
    Algorithm: Greedy assignment with weighted scoring
    
    Args:
        task_scope: List of tasks to allocate
        num_devices: Number of available emulators
    
    Returns:
        List[List]: Each sublist contains tasks assigned to one emulator
    """
    # Check for special attributes
    has_task_app = any(
        hasattr(t, "task_app") and getattr(t, "task_app", None)
        for t in task_scope
    )
    has_original_task_id = any(
        hasattr(t, "original_task_id") and getattr(t, "original_task_id", None)
        for t in task_scope
    )
    
    # Simple round-robin if no special attributes
    if not has_task_app and not has_original_task_id:
        return _simple_round_robin(task_scope, num_devices)
    
    # Initialize emulator groups and tracking
    groups = [[] for _ in range(num_devices)]
    device_task_apps = [set() for _ in range(num_devices)]
    device_original_ids = [set() for _ in range(num_devices)]
    
    # Perform allocation
    if has_task_app:
        _allocate_with_app_priority(
            task_scope, groups, device_task_apps, device_original_ids
        )
    elif has_original_task_id:
        _allocate_with_origin_priority(
            task_scope, groups, device_original_ids
        )
    
    # Remove empty groups
    groups = [g for g in groups if g]
    
    # Print allocation statistics
    _print_allocation_stats(
        task_scope, groups, has_task_app, has_original_task_id
    )
    
    return groups


def _simple_round_robin(task_scope, num_devices):
    """Simple round-robin task distribution."""
    groups = [[] for _ in range(num_devices)]
    for i, task in enumerate(task_scope):
        groups[i % num_devices].append(task)
    return [g for g in groups if g]


def _allocate_with_app_priority(task_scope, groups, device_task_apps, device_original_ids):
    """
    Allocate tasks prioritizing task_app diversity.
    
    Uses greedy algorithm with weighted scoring:
    - +1000 for task_app conflict (highest penalty)
    - +100 for original_task_id conflict
    - +1 per existing task (load balancing)
    """
    num_devices = len(groups)
    
    for task in task_scope:
        best_device = _find_best_device(
            task, num_devices, groups, device_task_apps, device_original_ids
        )
        
        # Assign to best device
        groups[best_device].append(task)
        
        # Update tracking
        task_app_value = getattr(task, "task_app", None)
        if task_app_value:
            device_task_apps[best_device].add(task_app_value)
        
        origin_id = getattr(task, "original_task_id", None)
        if origin_id:
            device_original_ids[best_device].add(origin_id)


def _allocate_with_origin_priority(task_scope, groups, device_original_ids):
    """Allocate tasks prioritizing original_task_id diversity."""
    num_devices = len(groups)
    
    for task in task_scope:
        origin_id = getattr(task, "original_task_id", None)
        
        # Find best device
        best_device = None
        best_score = None
        
        for device_idx in range(num_devices):
            score = 0
            
            # Check original_task_id conflict
            if origin_id and origin_id in device_original_ids[device_idx]:
                score += 100
            
            # Load balancing
            score += len(groups[device_idx])
            
            if best_score is None or score < best_score:
                best_score = score
                best_device = device_idx
        
        # Assign
        groups[best_device].append(task)
        
        if origin_id:
            device_original_ids[best_device].add(origin_id)


def _find_best_device(task, num_devices, groups, device_task_apps, device_original_ids):
    """
    Find the best device for a task using weighted scoring.
    
    Returns device index with lowest score (best fit).
    """
    best_device = None
    best_score = None
    
    for device_idx in range(num_devices):
        score = 0
        
        # Check task_app conflict (highest priority)
        task_app_value = getattr(task, "task_app", None)
        if task_app_value and task_app_value in device_task_apps[device_idx]:
            score += 1000
        
        # Check original_task_id conflict (secondary priority)
        origin_id = getattr(task, "original_task_id", None)
        if origin_id and origin_id in device_original_ids[device_idx]:
            score += 100
        
        # Load balancing
        score += len(groups[device_idx])
        
        if best_score is None or score < best_score:
            best_score = score
            best_device = device_idx
    
    return best_device


def _print_allocation_stats(task_scope, groups, has_task_app, has_original_task_id):
    """Print detailed allocation statistics."""
    print("\n" + "="*80)
    print("Task Distribution to Emulators")
    print("="*80)
    
    if has_task_app:
        all_apps = set(
            getattr(t, "task_app", None) for t in task_scope
            if getattr(t, "task_app", None)
        )
        print(f"Total unique task_apps: {len(all_apps)}")
    
    if has_original_task_id:
        all_origins = set(
            getattr(t, "original_task_id", None) for t in task_scope
            if getattr(t, "original_task_id", None)
        )
        print(f"Total unique original_task_ids: {len(all_origins)}")
    
    print(f"Total tasks: {len(task_scope)}")
    print(f"Number of emulator groups: {len(groups)}")
    print("-"*80)
    
    # Per-emulator statistics
    for i, group in enumerate(groups):
        print(f"\nEmulator {i}:")
        print(f"  Total tasks: {len(group)}")
        
        if has_task_app:
            _print_app_stats(group)
        
        if has_original_task_id:
            _print_origin_stats(group)
    
    print("="*80 + "\n")


def _print_app_stats(group):
    """Print task_app statistics for a group."""
    apps_in_group = set(
        getattr(task, "task_app", None) for task in group
        if getattr(task, "task_app", None)
    )
    print(f"  Unique task_apps: {len(apps_in_group)}")
    
    # Check conflicts
    app_counts = defaultdict(int)
    for task in group:
        app = getattr(task, "task_app", None)
        if app:
            app_counts[app] += 1
    
    conflicts = {app: count for app, count in app_counts.items() if count > 1}
    if conflicts:
        print(f"  WARNING: task_app conflicts: {conflicts}")


def _print_origin_stats(group):
    """Print original_task_id statistics for a group."""
    origins_in_group = set(
        getattr(task, "original_task_id", None) for task in group
        if getattr(task, "original_task_id", None)
    )
    print(f"  Unique original_task_ids: {len(origins_in_group)}")
    
    # Check conflicts
    origin_counts = defaultdict(int)
    for task in group:
        origin = getattr(task, "original_task_id", None)
        if origin:
            origin_counts[origin] += 1
    
    conflicts = {origin: count for origin, count in origin_counts.items() if count > 1}
    if conflicts:
        print(f"  WARNING: original_task_id conflicts: {conflicts}")

