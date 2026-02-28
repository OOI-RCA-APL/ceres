from ceres.data import StrEnum

__all__ = [
    "Connectivity",
]


class Connectivity(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
