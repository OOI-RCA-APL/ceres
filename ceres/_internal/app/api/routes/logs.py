from __future__ import annotations

from ceres._internal.app.shared import create_entity_router
from ceres.logs import LogEntry

router = create_entity_router(LogEntry, "logs", 1000)
