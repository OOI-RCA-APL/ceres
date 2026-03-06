from ceres.__internal__.cli.shared import create_entity_command
from ceres.logs import LogEntry

LogsCommand = create_entity_command(LogEntry, follow=True)
