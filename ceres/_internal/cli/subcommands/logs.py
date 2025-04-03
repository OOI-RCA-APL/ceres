from __future__ import annotations

from ceres._internal.cli.shared import create_entity_command
from ceres.logs import LogEntry

LogsCommand = create_entity_command(LogEntry, follow=True)
