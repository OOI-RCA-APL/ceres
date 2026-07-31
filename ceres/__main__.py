__all__ = []

if __name__ == "__main__":
    import sys

    from ceres.__internal__.cli.main import main

    # The exit code is the command's result, and the native CLI delegates by executing
    # this module, so discarding it would report success for every delegated failure.
    sys.exit(main())
