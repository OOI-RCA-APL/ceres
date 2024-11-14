from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Unpack, overload, override

from ceres._internal.lazy import lazy_imports
from ceres.message import MessageFilterArgs

with lazy_imports(__name__):
    import anyio

    from ceres._internal import util
    from ceres._internal.util import BytesLike
    from ceres.message import Message
    from ceres.roles.connection import Connection


@dataclass(kw_only=True, frozen=True)
class AttemptFailure:
    reason: str | None = None
    exception: Exception | None = None


class Transport:
    def __init__(self, connection: Connection) -> None:
        self.__connection = connection

    @property
    def connection(self) -> Connection:
        return self.__connection

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.__connection})"

    async def send(self, data: BytesLike) -> Message:
        return await self.connection.send(util.bytes_of(data))

    @overload
    async def receive(
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message: ...

    @overload
    async def receive[T](
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T],
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T: ...

    async def receive[T](
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T] | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T:
        if isinstance(timeout, timedelta):
            timeout = timeout.total_seconds()

        if kwargs:
            query = Message.Filter(**kwargs)
        else:
            query = None

        def fail() -> T:
            if default is ...:
                raise TimeoutError()
            if callable(default):
                return default()  # type: ignore
            return default  # type: ignore

        with anyio.move_on_after(timeout):
            async for message in self.__connection.system.messages.follow(
                direction=Message.Direction.RECEIVE
            ):
                if condition is not None:
                    if not condition(message):
                        return fail()
                if query is not None:
                    if not query.matches(message):
                        return fail()

                return message

        return fail()
