from ..tasks import ensure_event_loop
from .root import root


def main() -> None:
    ensure_event_loop()
    root()  # type: ignore
