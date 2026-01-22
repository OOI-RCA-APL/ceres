from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Unpack, overload, override

if TYPE_CHECKING:
    from collections.abc import Callable

    from ceres.connection import Connection
    from ceres.data import ToBytes
    from ceres.message import Message, MessageFilterArgs


class Transport:
    __slots__ = ("__connection",)

    def __init__(self, connection: Connection) -> None:
        self.__connection = connection

    @property
    def connection(self) -> Connection:
        return self.__connection

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.__connection})"

    async def send(self, data: ToBytes) -> Message:
        return await self.connection.send(data)

    @overload
    async def receive[T](
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T],
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T: ...

    @overload
    async def receive(
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: ... = ...,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message: ...

    async def receive[T](
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T] = ...,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T:
        received = self.__connection.messages.received.read()

        if isinstance(timeout, timedelta):
            timeout = timeout.total_seconds()

        if kwargs:
            from ceres.message import MessageFilter

            query = MessageFilter.model_validate(kwargs)
        else:
            query = None

        def fail() -> T:
            if default is ...:
                raise TimeoutError()
            if callable(default):
                return default()  # type: ignore
            return default  # type: ignore

        import anyio

        with anyio.move_on_after(timeout):
            async for message in received:
                if condition is not None:
                    if not condition(message):
                        return fail()
                if query is not None:
                    if not query.matches(message):
                        return fail()

                return message

        return fail()
