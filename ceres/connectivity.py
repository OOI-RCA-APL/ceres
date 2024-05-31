from __future__ import annotations

from ceres.data import StrEnum


class Connectivity(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
