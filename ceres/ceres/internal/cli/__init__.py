from ..utilities import setup_event_loop
from .root import root


def main() -> None:
    setup_event_loop()
    root()  # type: ignore
