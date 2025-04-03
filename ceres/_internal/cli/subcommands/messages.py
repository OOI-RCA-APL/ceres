from __future__ import annotations

from ceres._internal.cli.shared import create_entity_command
from ceres.message import Message

MessagesCommand = create_entity_command(Message, follow=True)
