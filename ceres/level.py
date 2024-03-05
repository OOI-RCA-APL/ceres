from ceres.data import PriorityStrEnum


class Level(PriorityStrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
