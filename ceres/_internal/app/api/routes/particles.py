from __future__ import annotations

from ceres._internal.app.shared import create_entity_router
from ceres.particle import Particle

router = create_entity_router(Particle, "particles", 5000)
