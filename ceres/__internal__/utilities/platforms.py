"""Boolean constants for detecting the current operating system and Python build variant."""

import platform
import sys

LINUX = platform.system() == "Linux"
"""``True`` when running on Linux."""

MACOS = platform.system() == "Darwin"
"""``True`` when running on macOS."""

WINDOWS = platform.system() == "Windows"
"""``True`` when running on Windows."""

UNIX = not WINDOWS
"""``True`` when running on any Unix-like system (not Windows)."""

FREE_THREADED = "free" in sys.version
"""``True`` when running on a free-threaded CPython build."""
