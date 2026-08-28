#!/usr/bin/env python3
"""七类拓扑任务的统一配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskSpec:
    name: str
    dataset_root: Path
    result_root: Path
    evaluation_root: Path
    answer_kind: str
    answer_field: str | None = None


def _spec(
    name: str,
    dataset_dir: str,
    answer_kind: str,
    answer_field: str | None = None,
) -> TaskSpec:
    return TaskSpec(
        name=name,
        dataset_root=Path(dataset_dir),
        result_root=Path("vllm-results") / name,
        evaluation_root=Path("vllm-results") / f"{name}-evaluation",
        answer_kind=answer_kind,
        answer_field=answer_field,
    )


TASK_SPECS = {
    "shortest_path": _spec(
        "shortest_path",
        "shortest_path_dataset",
        "extended_path",
    ),
    "uplink_node_path": _spec(
        "uplink_node_path",
        "uplink_node_path_dataset",
        "path",
    ),
    "node_failure_reroute": _spec(
        "node_failure_reroute",
        "node_failure_reroute_dataset",
        "path",
    ),
    "node_failure_ap_impact": _spec(
        "node_failure_ap_impact",
        "node_failure_ap_impact_dataset",
        "node_set",
        "impacted_ap_ids",
    ),
    "ap_pair_via_core_path": _spec(
        "ap_pair_via_core_path",
        "ap_pair_via_core_path_dataset",
        "path",
    ),
    "downstream_reachable_terminal": _spec(
        "downstream_reachable_terminal",
        "downstream_reachable_terminal_dataset",
        "node_set",
        "downstream_terminal_node_ids",
    ),
    "vlan_constrained_shortest_path": _spec(
        "vlan_constrained_shortest_path",
        "vlan_constrained_shortest_path_dataset",
        "path",
    ),
}


def get_task_spec(task_name: str) -> TaskSpec:
    try:
        return TASK_SPECS[task_name]
    except KeyError as error:
        raise ValueError(f"不支持的任务: {task_name}") from error
