#!/usr/bin/env uv run

import hashlib
import json
import re
import sys
from pathlib import Path
from subprocess import run
from typing import Any

# ruff: disable[T201] # Allow print statements.

PYTHON_MD_START = "<!-- coverage:python:start -->"
PYTHON_MD_END = "<!-- coverage:python:end -->"
RUST_MD_START = "<!-- coverage:rust:start -->"
RUST_MD_END = "<!-- coverage:rust:end -->"
BADGE_START = "<!-- coverage:badge -->"
BADGE_END = "<!-- /coverage:badge -->"
FINGERPRINT_PATTERN = re.compile(r"<!-- coverage:fingerprint:([0-9a-f]+) -->")


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


def _run_rust_coverage() -> dict[str, Any]:
    """Collect line coverage for the Rust workspace through `cargo llvm-cov`.

    Mirrors `make test`, one run over the default members and one over `ceres-core`,
    collected into a single report. Inline `#[cfg(test)]` modules are instrumented along
    with the code they test, so the percentages read a little higher than the source
    alone would.
    """
    for arguments in (
        ["cargo", "llvm-cov", "--no-report"],
        ["cargo", "llvm-cov", "--no-report", "-p", "ceres-core"],
    ):
        result = run(arguments, cwd="rust", capture_output=True, text=True)
        if result.returncode != 0:
            print("cargo llvm-cov failed:")
            print(result.stdout)
            print(result.stderr)
            sys.exit(1)

    result = run(
        ["cargo", "llvm-cov", "report", "--json", "--summary-only"],
        cwd="rust",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("cargo llvm-cov report failed:")
        print(result.stderr)
        sys.exit(1)

    return json.loads(result.stdout)


def _fingerprint() -> str:
    """Hash every file the coverage numbers are computed from.

    The check mode compares this against the hash recorded in `COVERAGE.md`, which tells
    CI whether the tables still describe the tree without rerunning either suite.
    Manifests and lock files stay out of the hash, because release version bumps touch
    them without moving any number.
    """
    digest = hashlib.sha256()
    for root, pattern in ((Path("ceres"), "*.py"), (Path("tests"), "*.py"), (Path("rust"), "*.rs")):
        for path in sorted(root.rglob(pattern)):
            if "target" in path.parts:
                continue

            digest.update(str(path).encode())
            digest.update(path.read_bytes())

    return digest.hexdigest()[:16]


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


def _badge_line(label: str, percent: int) -> str:
    color = _badge_color(percent)
    slug = label.lower().replace(" ", "%20")
    return f"![{label}: {percent}%](https://img.shields.io/badge/{slug}-{percent}%25-{color})"


def _build_python_table(data: dict[str, Any]) -> str:
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


def _build_rust_table(data: dict[str, Any]) -> str:
    export = data["data"][0]
    root = Path.cwd()

    lines = [
        "| Module | Coverage |",
        "|---|---|",
    ]
    for entry in sorted(export["files"], key=lambda entry: entry["filename"]):
        path = Path(entry["filename"])
        if path.is_absolute():
            path = path.relative_to(root)

        percent = round(entry["summary"]["lines"]["percent"])
        lines.append(f"| `{path}` | {percent}% |")

    total_percent = round(export["totals"]["lines"]["percent"])
    lines.append(f"| **Total** | **{total_percent}%** |")

    return "\n".join(lines)


def _update_between_markers(path: Path, start: str, end: str, content: str) -> None:
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

    if updated != original:
        path.write_text(updated)
        print(f"Updated {path}.")


def _check(fingerprint: str) -> None:
    """Compare the recorded fingerprint to the tree's, without running either suite."""
    match = FINGERPRINT_PATTERN.search(Path("COVERAGE.md").read_text())
    if match is None:
        print("COVERAGE.md records no fingerprint. Run `make coverage` to update.")
        sys.exit(1)

    if match.group(1) != fingerprint:
        print("COVERAGE.md is out of date. Run `make coverage` to update.")
        sys.exit(1)

    print("Everything is up to date.")


def __main__():
    fingerprint = _fingerprint()
    if "--check" in sys.argv:
        _check(fingerprint)
        return

    python = _run_coverage()
    rust = _run_rust_coverage()
    python_percent = round(python["totals"]["percent_covered"])
    rust_percent = round(rust["data"][0]["totals"]["lines"]["percent"])

    badges = "\n".join(
        [
            _badge_line("Python Coverage", python_percent),
            _badge_line("Rust Coverage", rust_percent),
        ]
    )
    # The README GitHub renders for the repository is the documentation's own home page,
    # so the badges live there rather than in a second copy at the root.
    _update_between_markers(Path("docs/README.md"), BADGE_START, BADGE_END, badges)

    coverage_md = Path("COVERAGE.md")
    _update_between_markers(
        coverage_md, PYTHON_MD_START, PYTHON_MD_END, _build_python_table(python)
    )
    _update_between_markers(coverage_md, RUST_MD_START, RUST_MD_END, _build_rust_table(rust))

    updated = FINGERPRINT_PATTERN.sub(
        f"<!-- coverage:fingerprint:{fingerprint} -->", coverage_md.read_text()
    )
    coverage_md.write_text(updated)


if __name__ == "__main__":
    try:
        __main__()
    except KeyboardInterrupt:
        print("Cancelled.")
