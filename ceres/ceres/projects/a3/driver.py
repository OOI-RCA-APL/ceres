from ceres import Component, Connection, Ref
from ceres.events import MessageReceivedEvent
from ceres.listener import on


class A3Driver(Component):
    host_connection: Ref[Connection]
    das_connection: Ref[Connection]

    @on(MessageReceivedEvent, ["host_connection", "das_connection"])
    def __on_message_received(self, event: MessageReceivedEvent) -> None:
        self.logger.info(event.message)
