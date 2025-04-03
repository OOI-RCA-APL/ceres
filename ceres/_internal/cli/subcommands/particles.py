from __future__ import annotations

from ceres._internal.cli.shared import create_entity_command
from ceres.particle import Particle

ParticlesCommand = create_entity_command(Particle, follow=True)
