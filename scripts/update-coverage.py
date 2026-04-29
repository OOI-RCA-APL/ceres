#!/usr/bin/env uv run

import json
import re
import sys
from pathlib import Path
from subprocess import run

# ruff: disable[T201] # Allow print statements.

README_START_MARKER = "<!-- coverage:start -->"
README_END_MARKER = "<!-- coverage:end -->"


def _run_coverage() -> dict[str, object]:
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


def _build_table(data: dict[str, object]) -> str:
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


def _update_readme(table: str, check: bool) -> bool:
    readme_path = Path("README.md")
    if not readme_path.exists():
        print("README.md not found.")
        sys.exit(1)

    content = readme_path.read_text()

    pattern = re.compile(
        rf"({re.escape(README_START_MARKER)})\n.*?\n({re.escape(README_END_MARKER)})",
        re.DOTALL,
    )

    match = pattern.search(content)
    if not match:
        print(f"Could not find {README_START_MARKER} / {README_END_MARKER} markers in README.md.")
        sys.exit(1)

    new_section = f"{README_START_MARKER}\n{table}\n{README_END_MARKER}"
    updated = pattern.sub(new_section, content)

    if updated == content:
        print("Coverage table is already up to date.")
        return True

    if check:
        print("Coverage table is out of date. Run `make coverage` to update.")
        return False

    readme_path.write_text(updated)
    print("Updated coverage table in README.md.")
    return True


def __main__():
    check = "--check" in sys.argv
    data = _run_coverage()
    table = _build_table(data)
    if not _update_readme(table, check):
        sys.exit(1)


if __name__ == "__main__":
    try:
        __main__()
    except KeyboardInterrupt:
        print("Cancelled.")
