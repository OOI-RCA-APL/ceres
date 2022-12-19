import asyncio
from abc import ABC, abstractmethod
from datetime import timedelta
from enum import Enum
from typing import Any, AsyncIterable

from pydantic import validator

from .alert import Alert, AlertLevel
from .component import Component
from .data import ImmutableDataObject, jsonify
from .events import (
    ConnectedEvent,
    DisconnectedEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from .exceptions import ConnectionLostException
from .internal.utilities import validate_positive_timedelta
from .message import Message, MessageDirection
from .procedure import query, subscription


class ConnectionReconnect(ImmutableDataObject):
    interval: timedelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: timedelta | None = timedelta(seconds=60)

    @validator("interval", "max_interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class _ReconnectScheduler:
    def __init__(self, config: ConnectionReconnect) -> None:
        self.__initial_interval = config.interval
        self.__current_interval = config.interval
        self.__max_interval = config.max_interval

        if config.backoff is not None:
            self.__backoff: float = config.backoff
        else:
            self.__backoff = 1

        self.__retries = 0

    def reset(self) -> None:
        self.__retries = 0

    def next(self) -> timedelta:
        interval = self.__current_interval * self.__backoff
        if self.__max_interval is not None and interval > self.__max_interval:
            interval = self.__max_interval
        self.__current_interval = interval
        self.__retries += 1

        return interval


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class Connection(Component, ABC):
    class Parameters(Component.Parameters):
        reconnect: ConnectionReconnect

    parameters: Parameters

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__state = ConnectionState.DISCONNECTED
        self.__reconnect = _ReconnectScheduler(self.parameters.reconnect)

    @property
    @abstractmethod
    def target(self) -> str:
        ...

    @property
    def state(self) -> ConnectionState:
        return self.__state

    @property
    def connected(self) -> bool:
        return self.__state == ConnectionState.CONNECTED

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
        if self.__state == ConnectionState.CONNECTED:
            return True

        self.logger.info("Connecting...")
        self.__state = ConnectionState.CONNECTING

        try:
            connected = await self.try_connect()
        except Exception as exception:
            connected = False
            if error := str(exception).strip():
                self.logger.error(error)

        if connected:
            self.__state = ConnectionState.CONNECTED
            self.emit_event(ConnectedEvent())
            self.logger.info("Connected successfully.")
        else:
            self.__state = ConnectionState.DISCONNECTED
            self.logger.error("Failed to connect.")

        return self.connected

    async def send(self, data: bytes) -> Message:
        try:
            await self.send_data(data)
        except ConnectionLostException:
            await self.disconnect()
            raise

        message = Message(
            component_id=self.context.id,
            direction=MessageDirection.SEND,
            content=data,
        )

        self.logger.info(f"Sent: {jsonify(message.content)}")

        self.emit_event(MessageSentEvent(message=message))

        return message

    async def receive(self) -> Message:
        try:
            data = await self.receive_data()
        except ConnectionLostException:
            await self.disconnect()
            raise

        message = Message(
            component_id=self.context.id,
            direction=MessageDirection.RECEIVE,
            content=data,
        )

        self.logger.info(f"Received: {jsonify(message.content)}")
        self.emit_event(MessageReceivedEvent(message=message))

        return message

    async def disconnect(self) -> None:
        if self.__state == ConnectionState.DISCONNECTED:
            return

        self.logger.info("Disconnecting...")

        try:
            await self.try_disconnect()
        finally:
            self.__state = ConnectionState.DISCONNECTED
            self.emit_event(DisconnectedEvent())
            self.logger.info("Disconnected.")

    async def __run__(self) -> None:
        await asyncio.gather(
            super().__run__(),
            self.__process_update(),
        )

    async def __process_update(self) -> None:
        while True:
            self.__reconnect.reset()

            while not await self.connect():
                self.emit_alert(
                    Alert(
                        level=AlertLevel.ERROR,
                        code="connection-attempt-failed",
                    )
                )
                seconds = self.__reconnect.next().total_seconds()
                self.logger.info(f"Reconnecting in {seconds:g} seconds...")
                await asyncio.sleep(seconds)

            while self.connected:
                try:
                    await self.receive()
                except Exception as exception:
                    if error := str(exception).strip():
                        self.logger.error(error)

    async def __stop__(self) -> None:
        await super().__stop__()
        await self.try_disconnect()

    @query("connection-state")
    async def get_connection_state(self) -> ConnectionState:
        return self.__state

    @subscription("connection-state")
    async def subscribe_connection_state(self) -> AsyncIterable[ConnectionState]:
        yield await self.get_connection_state()
        async for event in self.events:
            if isinstance(event, ConnectedEvent | DisconnectedEvent):
                yield self.__state
