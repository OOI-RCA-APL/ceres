import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any

from pydantic import validator
from pydantic.dataclasses import dataclass as validated_dataclass

from .address import LocalComponentAddress
from .component import Component, ComponentContext, ComponentParameters
from .events import (
    ConnectedEvent,
    DisconnectedEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from .exceptions import ConnectionLostException
from .internal.utilities import jsonify, validate_positive_timedelta
from .message import Message, MessageDirection
from .stream import Stream, StreamView


@validated_dataclass(kw_only=True, frozen=True)
class ConnectionReconnect:
    interval: timedelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: timedelta | None = timedelta(seconds=60)

    @validator("interval", "max_interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class ReconnectScheduler:
    def __init__(self, config: ConnectionReconnect) -> None:
        self.interval = config.interval
        self.max_interval = config.max_interval

        if config.backoff is not None:
            self.backoff: float = config.backoff
        else:
            self.backoff = 1

        self._retries = 0

    def reset(self) -> None:
        self._retries = 0

    def next(self) -> timedelta:
        next = self.interval * self.backoff**self._retries
        if self.max_interval is not None and next > self.max_interval:
            next = self.max_interval
        self._retries += 1
        return next


@validated_dataclass(kw_only=True, frozen=True)
class ConnectionParameters(ComponentParameters):
    reconnect: ConnectionReconnect


@validated_dataclass(kw_only=True, frozen=True)
class ConnectionContext(ComponentContext):
    pass


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass(kw_only=True)
class ConnectionInternal:
    state: ConnectionState
    last_message_sent: Message | None
    last_message_received: Message | None
    reconnect: ReconnectScheduler
    message_stream: Stream[Message]


@dataclass
class Connection(Component):
    parameters: ConnectionParameters
    context: ConnectionContext

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__connection_internal__ = ConnectionInternal(
            state=ConnectionState.DISCONNECTED,
            last_message_sent=None,
            last_message_received=None,
            reconnect=ReconnectScheduler(self.parameters.reconnect),
            message_stream=Stream(),
        )

    @property
    def state(self) -> ConnectionState:
        return self.__connection_internal__.state

    @property
    def connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    @property
    def last_message_sent(self) -> Message | None:
        return self.__connection_internal__.last_message_sent

    @property
    def last_message_received(self) -> Message | None:
        return self.__connection_internal__.last_message_received

    @property
    def message_stream(self) -> StreamView[Message]:
        return self.__connection_internal__.message_stream.view()

    def emit_message(self, message: Message) -> Message:
        self.__connection_internal__.message_stream.put(message)
        return message

    @abstractmethod
    async def try_connect(self) -> bool:
        ...

    @abstractmethod
    async def try_disconnect(self) -> None:
        ...

    @abstractmethod
    async def send_data(self, data: bytes) -> None:
        ...

    @abstractmethod
    async def receive_data(self) -> bytes:
        ...

    async def connect(self) -> bool:
        if self.state == ConnectionState.CONNECTED:
            return True

        self.logger.info("Connecting...")

        self.__connection_internal__.state = ConnectionState.CONNECTING

        try:
            connected = await self.try_connect()
        except Exception as exception:
            connected = False
            if error := str(exception).strip():
                self.logger.error(error)

        if connected:
            self.__connection_internal__.state = ConnectionState.CONNECTED
            self.emit_event(
                ConnectedEvent(
                    address=LocalComponentAddress(self.context.address.name),
                )
            )
            self.logger.info("Connected successfully.")
        else:
            self.__connection_internal__.state = ConnectionState.DISCONNECTED
            self.logger.error("Failed to connect.")

        return self.connected

    async def send(self, data: bytes) -> Message:
        try:
            await self.send_data(data)
        except ConnectionLostException:
            await self.disconnect()
            raise

        message = Message(
            connection_id=self.context.id,
            direction=MessageDirection.SEND,
            content=data,
        )

        self.logger.info(f"Sent: {jsonify(message.content)}")

        self.emit_message(message)
        self.emit_event(
            MessageSentEvent(
                address=LocalComponentAddress(self.context.address.name),
                message=message,
            )
        )

        self.__connection_internal__.last_message_sent = message

        return message

    async def receive(self) -> Message:
        try:
            data = await self.receive_data()
        except ConnectionLostException:
            await self.disconnect()
            raise

        message = Message(
            connection_id=self.context.id,
            direction=MessageDirection.RECEIVE,
            content=data,
        )

        self.logger.info(f"Received: {jsonify(message.content)}")

        self.emit_message(message)
        self.emit_event(
            MessageReceivedEvent(
                address=LocalComponentAddress(self.context.address.name),
                message=message,
            )
        )

        self.__connection_internal__.last_message_received = message
        return message

    async def disconnect(self) -> None:
        if self.state == ConnectionState.DISCONNECTED:
            return

        self.logger.info("Disconnecting...")

        try:
            await self.try_disconnect()
        finally:
            self.__connection_internal__.state = ConnectionState.DISCONNECTED
            self.emit_event(
                DisconnectedEvent(
                    address=LocalComponentAddress(self.context.address.name),
                )
            )

            self.logger.info("Disconnected.")

    async def _tasklet_run(self) -> None:
        await asyncio.gather(
            super()._tasklet_run(),
            self._process_update(),
        )

    async def _process_update(self) -> None:
        while True:
            self.__connection_internal__.reconnect.reset()

            while not await self.connect():
                self.emit_alert("error", "connection-attempt-failed")
                seconds = self.__connection_internal__.reconnect.next().total_seconds()
                self.logger.info(f"Reconnecting in {seconds:g} seconds...")
                await asyncio.sleep(seconds)

            while self.connected:
                try:
                    await self.receive()
                except Exception as exception:
                    if error := str(exception).strip():
                        self.logger.error(error)

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()
        await self.try_disconnect()
