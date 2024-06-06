import csv
from datetime import datetime
from pathlib import Path

from ceres import Component, Connection, Message, Ref, listener
from ceres.data import DataObject
from ceres.event import MessageReceivedEvent
from ceres.parsing import Parser


class Driver(Component):
    connection: Ref[Connection]
    out: Path

    @listener(reference="connection", event=MessageReceivedEvent)
    async def on__message(self, event: MessageReceivedEvent) -> None:
        data = MessageData.parse(event.message)

        self.out.parent.mkdir(parents=True, exist_ok=True)
        with self.out.open("a+") as file:
            writer = csv.writer(file)
            row = [
                data.timestamp.isoformat(),
                data.temperature,
                data.humidity,
            ]

            self.system.log.info(row)
            writer.writerow(row)


class MessageData(DataObject):
    timestamp: datetime
    temperature: float
    humidity: float

    @classmethod
    def parse(cls, message: Message) -> "MessageData":
        parser = Parser(message.content)
        parser.eat(b"T:")
        temperature = parser.eat_float()
        parser.eat_space()
        parser.eat(b"H:")
        humidity = parser.eat_float()

        return MessageData(
            timestamp=message.timestamp,
            temperature=temperature,
            humidity=humidity,
        )
