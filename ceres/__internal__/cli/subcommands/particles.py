from ceres.__internal__.cli.shared import create_entity_command
from ceres.particle import Particle

ParticlesCommand = create_entity_command(Particle, follow=True)
