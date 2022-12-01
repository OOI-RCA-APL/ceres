import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any

from pydantic import validator

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


class ConnectionReconnect(ImmutableDataObject):
    interval: timedelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: timedelta | None = timedelta(seconds=60)

    @validator("interval", "max_interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class _ReconnectScheduler:
    def __init__(self, config: ConnectionReconnect) -> None:
        self._initial_interval = config.interval
        self._current_interval = config.interval
        self._max_interval = config.max_interval

        if config.backoff is not None:
            self._backoff: float = config.backoff
        else:
            self._backoff = 1

        self._retries = 0

    def reset(self) -> None:
        self._retries = 0

    def next(self) -> timedelta:
        interval = self._current_interval * self._backoff
        if self._max_interval is not None and interval > self._max_interval:
            interval = self._max_interval
        self._current_interval = interval
        self._retries += 1

        return interval


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass(kw_only=True)
class ConnectionInternal:
    state: ConnectionState
    last_message_sent: Message | None
    last_message_received: Message | None
    reconnect: _ReconnectScheduler


class Connection(Component, ABC):
    class Parameters(Component.Parameters):
        reconnect: ConnectionReconnect

    parameters: Parameters

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__connection_internal__ = ConnectionInternal(
            state=ConnectionState.DISCONNECTED,
            last_message_sent=None,
            last_message_received=None,
            reconnect=_ReconnectScheduler(self.parameters.reconnect),
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
            self.emit_event(ConnectedEvent(address=self.address))
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
            component_id=self.context.id,
            direction=MessageDirection.SEND,
            content=data,
        )

        self.logger.info(f"Sent: {jsonify(message.content)}")

        self.emit_event(
            MessageSentEvent(
                address=self.address,
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
            component_id=self.context.id,
            direction=MessageDirection.RECEIVE,
            content=data,
        )

        self.logger.info(f"Received: {jsonify(message.content)}")

        self.emit_event(
            MessageReceivedEvent(
                address=self.address,
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
            self.emit_event(DisconnectedEvent(address=self.address))
            self.logger.info("Disconnected.")

    async def __run__(self) -> None:
        await asyncio.gather(
            super().__run__(),
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

    async def __stop__(self) -> None:
        await super().__stop__()
        await self.try_disconnect()
