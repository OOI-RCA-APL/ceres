from ceres.__internal__.cli.shared import create_entity_command
from ceres.alert import Alert

AlertsCommand = create_entity_command(Alert, follow=True)
