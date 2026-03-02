from ceres._internal.app.shared import create_record_router
from ceres.particle import Particle

router = create_record_router("particles", Particle, limit=5000)
