from __future__ import annotations

from ..tasks import ensure_event_loop
from .root import root


def main() -> None:
    ensure_event_loop()
    root()
