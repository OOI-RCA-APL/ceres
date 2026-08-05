"""Run the Python half of the Ceres CLI directly.

This is the module the native binary delegates to for the engine-hosting commands. It
must stay distinct from `python -m ceres`, which execs the binary, or the two would hand
off to each other forever.
"""

__all__ = []

if __name__ == "__main__":
    import sys

    from ceres.__internal__.cli.main import main

    # The exit code is the command's result, and the native CLI delegates by executing
    # this module, so discarding it would report success for every delegated failure.
    sys.exit(main())
