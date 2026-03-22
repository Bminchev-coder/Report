#!/usr/bin/env python3
"""Create a Report folder and total hours from task descriptions."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HOUR_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskHours:
    description: str
    hours: float


def parse_hours(line: str) -> float:
    total = 0.0
    for match in HOUR_PATTERN.finditer(line):
        value = float(match.group("value"))
        unit = match.group("unit").lower()
        if unit.startswith("m"):
            total += value / 60.0
        else:
            total += value
    return total


def load_tasks(lines: Iterable[str]) -> list[TaskHours]:
    tasks = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        hours = parse_hours(line)
        tasks.append(TaskHours(description=line, hours=hours))
    return tasks


def write_report(report_dir: Path, tasks: list[TaskHours]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "summary.md"
    total_hours = sum(task.hours for task in tasks)
    with report_path.open("w", encoding="utf-8") as handle:
        handle.write("# Work Report\n\n")
        handle.write("## Task Summary\n\n")
        if tasks:
            for task in tasks:
                handle.write(f"- {task.description} → {task.hours:.2f} hours\n")
        else:
            handle.write("- No tasks provided.\n")
        handle.write("\n")
        handle.write(f"**Total Hours:** {total_hours:.2f}\n")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Report folder and calculate total hours from task descriptions."
    )
    parser.add_argument(
        "task_file",
        nargs="?",
        default="tasks.txt",
        help="Path to a text file with task descriptions and time markers.",
    )
    parser.add_argument(
        "--report-dir",
        default="Report",
        help="Directory name for the generated report.",
    )
    args = parser.parse_args()

    task_path = Path(args.task_file)
    if task_path.exists():
        lines = task_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    tasks = load_tasks(lines)
    report_path = write_report(Path(args.report_dir), tasks)

    total_hours = sum(task.hours for task in tasks)
    print(f"Report saved to: {report_path}")
    print(f"Total hours: {total_hours:.2f}")


if __name__ == "__main__":
    main()
