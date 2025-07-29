from __future__ import annotations

from ceres._internal.app.shared import create_record_router
from ceres.alert import Alert

router = create_record_router("alerts", Alert)
