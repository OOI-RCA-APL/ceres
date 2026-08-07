"""Run the Ceres CLI.

`python -m ceres` hands straight off to the native `ceres` binary installed beside the
interpreter, so both invocations serve the same command surface. The binary delegates the
engine-hosting commands back to this environment's interpreter through
`ceres.__internal__.cli`, a separate module path, so the handoff cannot loop.
"""

__all__ = []


def _find_binary() -> str | None:
    """Locate the native `ceres` binary installed beside this interpreter."""
    import shutil
    import sys
    from pathlib import Path

    name = "ceres.exe" if sys.platform == "win32" else "ceres"
    beside = Path(sys.executable).parent / name
    if beside.is_file():
        return str(beside)

    return shutil.which("ceres")


if __name__ == "__main__":
    import os
    import subprocess
    import sys

    binary = _find_binary()
    if binary is None:
        # No binary means an environment without the compiled CLI, so the Python CLI
        # serves what it can directly.
        from ceres.__internal__.cli.main import main

        sys.exit(main())

    # This interpreter is the one Ceres is importable from, so the binary delegates the
    # engine-hosting commands back to exactly it rather than rediscovering one.
    environment = dict(os.environ)
    environment.setdefault("CERES_PYTHON", sys.executable)

    if sys.platform == "win32":
        # Windows has no true exec, so run the binary as a child and mirror its result.
        sys.exit(subprocess.run([binary, *sys.argv[1:]], env=environment).returncode)

    os.execve(binary, [binary, *sys.argv[1:]], environment)
