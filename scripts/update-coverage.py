#!/usr/bin/env uv run

import json
import re
import sys
from pathlib import Path
from subprocess import run
from typing import Any

# ruff: disable[T201] # Allow print statements.

COVERAGE_MD_START = "<!-- coverage:start -->"
COVERAGE_MD_END = "<!-- coverage:end -->"
BADGE_START = "<!-- coverage:badge -->"
BADGE_END = "<!-- /coverage:badge -->"


def _run_coverage() -> dict[str, Any]:
    result = run(
        ["uv", "run", "pytest", "--cov", "--cov-report=json", "-q"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("pytest failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)

    coverage_path = Path("coverage.json")
    if not coverage_path.exists():
        print("coverage.json not found. Is pytest-cov installed?")
        sys.exit(1)

    data = json.loads(coverage_path.read_text())
    coverage_path.unlink()
    return data


def _badge_color(percent: int) -> str:
    if percent >= 90:
        return "brightgreen"
    if percent >= 75:
        return "yellowgreen"
    if percent >= 60:
        return "yellow"
    if percent >= 40:
        return "orange"
    return "red"


def _badge_line(percent: int) -> str:
    color = _badge_color(percent)
    return f"![Coverage: {percent}%](https://img.shields.io/badge/coverage-{percent}%25-{color})"


def _build_table(data: dict[str, Any]) -> str:
    files = data["files"]
    totals = data["totals"]

    rows: list[tuple[str, int]] = []
    for filepath, info in sorted(files.items()):
        percent = round(info["summary"]["percent_covered"])
        rows.append((filepath, percent))

    total_percent = round(totals["percent_covered"])

    lines = [
        "| Module | Coverage |",
        "|---|---|",
    ]
    for filepath, percent in rows:
        lines.append(f"| `{filepath}` | {percent}% |")
    lines.append(f"| **Total** | **{total_percent}%** |")

    return "\n".join(lines)


def _update_between_markers(path: Path, start: str, end: str, content: str, check: bool) -> bool:
    if not path.exists():
        print(f"{path} not found.")
        sys.exit(1)

    original = path.read_text()

    pattern = re.compile(
        rf"({re.escape(start)})\n.*?({re.escape(end)})",
        re.DOTALL,
    )

    if not pattern.search(original):
        print(f"Could not find {start} / {end} markers in {path}.")
        sys.exit(1)

    updated = pattern.sub(rf"\g<1>\n{content}\n\g<2>", original)

    if updated == original:
        return True

    if check:
        print(f"{path} is out of date. Run `make coverage` to update.")
        return False

    path.write_text(updated)
    print(f"Updated {path}.")
    return True


def __main__():
    check = "--check" in sys.argv
    data = _run_coverage()
    total_percent = round(data["totals"]["percent_covered"])

    ok = True
    ok &= _update_between_markers(
        Path("README.md"), BADGE_START, BADGE_END, _badge_line(total_percent), check
    )
    ok &= _update_between_markers(
        Path("COVERAGE.md"), COVERAGE_MD_START, COVERAGE_MD_END, _build_table(data), check
    )

    if not ok:
        sys.exit(1)

    if check:
        print("Everything is up to date.")


if __name__ == "__main__":
    try:
        __main__()
    except KeyboardInterrupt:
        print("Cancelled.")
