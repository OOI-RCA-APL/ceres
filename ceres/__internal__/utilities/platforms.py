import platform
import sys

LINUX = platform.system() == "Linux"
MACOS = platform.system() == "Darwin"
WINDOWS = platform.system() == "Windows"
UNIX = not WINDOWS
FREE_THREADED = "free" in sys.version
