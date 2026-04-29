#!/usr/bin/env uv run

import json
import re
import sys
from pathlib import Path
from subprocess import run
from xml.etree.ElementTree import Element, SubElement, tostring

# ruff: disable[T201] # Allow print statements.

COVERAGE_MD_START = "<!-- coverage:start -->"
COVERAGE_MD_END = "<!-- coverage:end -->"


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


def _badge_color(percent: int) -> str:
    if percent >= 90:
        return "#4c1"
    if percent >= 75:
        return "#a3c51c"
    if percent >= 60:
        return "#dfb317"
    if percent >= 40:
        return "#fe7d37"
    return "#e05d44"


def _build_badge_svg(percent: int) -> str:
    label = "coverage"
    value = f"{percent}%"
    label_width = 62
    value_width = 46
    total_width = label_width + value_width
    color = _badge_color(percent)

    svg = Element(
        "svg",
        xmlns="http://www.w3.org/2000/svg",
        width=str(total_width),
        height="20",
    )

    linear_gradient = SubElement(
        SubElement(svg, "defs"),
        "linearGradient",
        id="s",
        x2="0",
        y2="100%",
    )
    SubElement(linear_gradient, "stop", offset="0", **{"stop-color": "#bbb", "stop-opacity": ".1"})
    SubElement(linear_gradient, "stop", offset="1", **{"stop-opacity": ".1"})

    mask = SubElement(svg, "mask", id="m")
    SubElement(mask, "rect", width=str(total_width), height="20", rx="3", fill="#fff")

    group = SubElement(svg, "g", mask="url(#m)")
    SubElement(group, "rect", width=str(label_width), height="20", fill="#555")
    SubElement(group, "rect", x=str(label_width), width=str(value_width), height="20", fill=color)
    SubElement(group, "rect", width=str(total_width), height="20", fill="url(#s)")

    text_group = SubElement(
        svg, "g", fill="#fff", **{"font-family": "sans-serif", "font-size": "11"}
    )
    for text, x_pos in [(label, label_width / 2), (value, label_width + value_width / 2)]:
        shadow = SubElement(text_group, "text", x=str(x_pos), y="15", fill="#010101")
        shadow.set("fill-opacity", ".3")
        shadow.set("text-anchor", "middle")
        shadow.text = text
        foreground = SubElement(text_group, "text", x=str(x_pos), y="14")
        foreground.set("text-anchor", "middle")
        foreground.text = text

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(svg, encoding="unicode")


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


def _update_file(path: Path, table: str, check: bool) -> bool:
    if not path.exists():
        print(f"{path} not found.")
        sys.exit(1)

    content = path.read_text()

    pattern = re.compile(
        rf"({re.escape(COVERAGE_MD_START)})\n.*?({re.escape(COVERAGE_MD_END)})",
        re.DOTALL,
    )

    if not pattern.search(content):
        print(f"Could not find coverage markers in {path}.")
        sys.exit(1)

    new_section = f"{COVERAGE_MD_START}\n{table}\n{COVERAGE_MD_END}"
    updated = pattern.sub(new_section, content)

    if updated == content:
        print(f"{path} is already up to date.")
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

    badge_svg = _build_badge_svg(total_percent)
    badge_path = Path("ceres/static/coverage.svg")
    badge_path.parent.mkdir(parents=True, exist_ok=True)

    if check:
        if badge_path.exists() and badge_path.read_text() == badge_svg:
            print("Badge is already up to date.")
        else:
            print("Badge is out of date. Run `make coverage` to update.")
            sys.exit(1)
    else:
        badge_path.write_text(badge_svg)
        print(f"Updated {badge_path}.")

    table = _build_table(data)
    ok = _update_file(Path("COVERAGE.md"), table, check)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    try:
        __main__()
    except KeyboardInterrupt:
        print("Cancelled.")
