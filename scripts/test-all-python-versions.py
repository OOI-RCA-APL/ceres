#!/usr/bin/env uv run
# Shebang line to specify the Python interpreter to use for this script.

import re
import sys
from argparse import ArgumentParser
from os import chdir
from subprocess import DEVNULL, run
from typing import Literal

from packaging.version import Version

from ceres._internal.util import uniquify
from ceres.paths import proj

SUPPORTED_VERSIONS = ["3.14"]

# ruff: disable[T201] # Allow print statements.


def _get_version_from_output(output: str) -> Version:
    match = re.search(r"\d+\.\d+.\d+", output)
    if not match:
        raise RuntimeError(f"Could not parse Python version from output {output!r}.")

    return Version(match.group())


def _get_python_version() -> Version:
    output = run(
        ["python", "--version"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    return _get_version_from_output(output)


def _set_python_version(
    version: Version | str,
    mode: Literal["exact", "lowest", "highest"] = "exact",
) -> Version:
    version = str(version)
    parsed = Version(version)
    is_major_only = len(parsed.release) == 1
    is_minor_only = len(parsed.release) == 2
    is_exact = len(parsed.release) == 3

    if mode == "lowest":
        if is_major_only:
            version = f"{version}.0.0"
        elif is_minor_only:
            version = f"{version}.0"

        run(["uv", "python", "install", version], check=True)
        run(["uv", "python", "pin", version], check=True, stdout=DEVNULL)
    elif mode == "highest" and not is_exact:
        installed = _get_version_from_output(
            run(
                ["uv", "python", "install", "--reinstall", "--upgrade", version],
                check=True,
                capture_output=True,
                text=True,
            ).stderr.strip()
        )
        _set_python_version(installed)
    else:
        run(["uv", "python", "install", version], check=True)
        run(["uv", "python", "pin", version], check=True, stdout=DEVNULL)

    run(["uv", "sync"], check=True)
    return _get_python_version()


def __main__():
    parser = ArgumentParser(description="Run tests with various Python versions.")
    parser.add_argument(
        "--lowest",
        action="store_true",
        help="Test lowest compatible Python versions",
    )
    parser.add_argument(
        "--highest",
        action="store_true",
        help="Test highest compatible Python versions",
    )
    parser.add_argument(
        "--min",
        type=str,
        help="Minimum Python version to test (e.g., '3.12')",
    )
    parser.add_argument(
        "--max",
        type=str,
        help="Maximum Python version to test (e.g., '3.14')",
    )
    parser.add_argument("--pytest", nargs="*", help="Arguments to pass to `pytest`.")
    parser.add_argument(
        "versions",
        nargs="*",
        help="Specific Python versions to test (e.g., '3.12' '3.13')",
    )

    args = parser.parse_args()
    min = Version(args.min) if args.min else None
    max = Version(args.max) if args.max else None
    lowest: bool = args.lowest
    highest: bool = args.highest
    if lowest and highest:
        parser.error("Cannot specify both --lowest and --highest.")

    # Determine which modes to test.
    if args.lowest:
        modes = ("lowest",)
    elif args.highest:
        modes = ("highest",)
    else:
        modes = ("lowest", "highest")

    chdir(proj())

    initial = _get_python_version()
    print(f"Initial Python version: {initial}.")

    # Determine which versions to test.
    versions_to_test = [Version(version) for version in (args.versions or SUPPORTED_VERSIONS)]

    # Filter versions based on `--min` and `--max`.
    filtered_versions: list[Version] = []
    for version in versions_to_test:
        if min is not None and version < min:
            continue
        if max is not None and version > max:
            continue

        filtered_versions.append(version)

    versions_to_test = uniquify(filtered_versions)
    tested_versions: set[Version] = set()

    pytest_args: list[str] = []
    if args.pytest:
        for current in args.pytest:
            pytest_args.extend(current.split(" "))

    passed: list[Version] = []
    failed: list[Version] = []

    try:
        for version in versions_to_test:
            for mode in modes:
                exact = _set_python_version(version, mode)
                if exact in tested_versions:
                    continue

                tested_versions.add(exact)

                print(f"Testing with Python {exact}.")
                if run(["uv", "run", "pytest", *pytest_args]).returncode == 0:
                    print(f"Tests passed for Python {exact}.")
                    passed.append(exact)
                else:
                    print(f"Tests failed for Python {exact}.")
                    failed.append(exact)

        print("Testing complete.")
    finally:
        print(f"Restoring initial Python version {initial}.")
        _set_python_version(initial)

        print(f"PASSED VERSIONS: {', '.join(str(version) for version in passed) or '(None)'}")
        print(f"FAILED VERSIONS: {', '.join(str(version) for version in failed) or '(None)'}")
        print(f"Current Python version was restored to {initial}.")

        sys.stdout.flush()


if __name__ == "__main__":
    try:
        __main__()
    except KeyboardInterrupt:
        print("Testing cancelled by user.")
