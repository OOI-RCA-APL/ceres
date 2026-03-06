from ceres.__internal__.app.shared import create_record_router
from ceres.logs import LogEntry

router = create_record_router("logs", LogEntry)
