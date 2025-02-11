from __future__ import annotations

from ceres._internal.app.shared import create_entity_router
from ceres.alert import Alert

router = create_entity_router(Alert, "alerts", 1000)
