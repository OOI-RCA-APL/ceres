from ceres.data import StrEnum

__all__ = [
    "Connectivity",
]


class Connectivity(StrEnum):
    """Represent the current connection state of a `Connection`.

    A connection moves through these states as it attempts to establish or maintain
    its underlying transport, the engine surfaces this state to interested observers.
    """

    DISCONNECTED = "disconnected"
    """The connection has no active transport and is not currently attempting to open one."""

    CONNECTING = "connecting"
    """The connection is actively attempting to establish its transport."""

    CONNECTED = "connected"
    """The connection has an active transport ready to send and receive data."""
