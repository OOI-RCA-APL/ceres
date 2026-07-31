"""Exit codes the CLI reports to the shell.

`python -m ceres` is how the native CLI delegates the commands it cannot serve, so an
exit code lost in the module entry point is a failure reported as success, both to a
shell script and through the binary.
"""

import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).parent.parent.parent.parent


def _run(*arguments: str, cwd: Path) -> int:
    """Run the CLI as a module and return its exit status."""
    return subprocess.run(
        [sys.executable, "-m", "ceres", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).returncode


def test_a_failing_command_exits_nonzero(tmp_path: Path) -> None:
    """A command that fails reports its failure to the shell.

    Run outside a project so the command fails on configuration, which is the cheapest
    failure that reaches the exit path every command shares.
    """
    assert _run("users", "select", "--no-color", cwd=tmp_path) == 1


def test_an_argument_error_exits_nonzero(tmp_path: Path) -> None:
    """An unparsable invocation exits with the argument-error status."""
    assert _run("users", "select", "--nosuchflag", "x", "--no-color", cwd=tmp_path) == 2


def test_a_successful_command_exits_zero(tmp_path: Path) -> None:
    """A command that succeeds reports success."""
    assert _run("--version", cwd=REPOSITORY) == 0
