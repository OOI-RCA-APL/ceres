#!/usr/bin/env python3

"""Build the `ceres` alias wheel for one release.

The alias is a pure-Python distribution whose only content is a pinned dependency on
`ceres-engine`, so the bare name resolves on the project's package index while the real
wheels build once under the distribution name. It generates a throwaway project and
builds it with `uv`, keeping the wheel's metadata a build backend's business.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

# ruff: disable[T201] # Allow print statements.


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the ceres alias wheel.")
    parser.add_argument("version", help="The release version the alias pins.")
    parser.add_argument("output", type=Path, help="Directory to write the wheel into.")
    options = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[build-system]",
                    'requires = ["hatchling"]',
                    'build-backend = "hatchling.build"',
                    "",
                    "[project]",
                    'name = "ceres"',
                    f'version = "{options.version}"',
                    'description = "Ceres, installed through its ceres-engine distribution."',
                    'requires-python = ">=3.14"',
                    f'dependencies = ["ceres-engine=={options.version}"]',
                    "",
                    "[tool.hatch.build.targets.wheel]",
                    "bypass-selection = true",
                    "",
                ]
            )
        )
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(options.output.resolve())],
            cwd=root,
            check=True,
        )

    print(f"Built the ceres=={options.version} alias wheel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
