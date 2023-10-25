from ceres.internal.utilities import StrEnum


class Connectivity(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
