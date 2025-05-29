from __future__ import annotations

from ceres._internal.app.shared import create_record_router
from ceres.logs import LogEntry

router = create_record_router("logs", LogEntry)
