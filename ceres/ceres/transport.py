from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, TypeVar

import anyio
from pydantic.fields import Undefined, UndefinedType
from typing_extensions import Unpack, overload

from ceres.component import MessageQuery, MessageQueryArgs
from ceres.internal.utilities import BytesLike, bytes_of
from ceres.message import Message
from ceres.roles.connection import Connection

_T = TypeVar("_T")


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

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.__connection})"

    async def send(self, data: BytesLike) -> Message:
        return await self.connection.send_message(bytes_of(data))

    @overload
    async def receive(
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        **kwargs: Unpack[MessageQueryArgs],
    ) -> Message:
        ...

    @overload
    async def receive(
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: _T | Callable[[], _T] | UndefinedType = Undefined,
        **kwargs: Unpack[MessageQueryArgs],
    ) -> Message | _T:
        ...

    async def receive(
        self,
        *,
        condition: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: _T | Callable[[], _T] | UndefinedType = Undefined,
        **kwargs: Unpack[MessageQueryArgs],
    ) -> Message | _T:
        if isinstance(timeout, timedelta):
            timeout = timeout.total_seconds()

        if kwargs:
            query = MessageQuery(**kwargs)
        else:
            query = None

        def fail() -> _T:
            if default is Undefined:
                raise TimeoutError()
            if callable(default):
                return default()
            return default  # type: ignore

        async with anyio.move_on_after(timeout):
            async for message in self.__connection.received:
                if condition is not None:
                    if not condition(message):
                        return fail()
                if query is not None:
                    if not query.matches(message):
                        return fail()

                return message

        return fail()
