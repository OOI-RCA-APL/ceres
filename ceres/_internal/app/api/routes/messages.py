from __future__ import annotations

from ceres._internal.app.shared import create_entity_router
from ceres.message import Message

router = create_entity_router(Message, "messages", 1000)
