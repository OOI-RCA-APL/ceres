from ceres.__internal__.cli.shared import create_entity_command
from ceres.message import Message

MessagesCommand = create_entity_command(Message, follow=True)
