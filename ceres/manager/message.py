from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterable, Unpack, override

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres.message import Message, MessageFilter, MessageFilterArgs

with lazy_imports(__name__):
    from ceres._internal import util
    from ceres.database import Database
    from ceres.node import Node
    from ceres.stream import Stream


class MessageManager(
    BaseEntityManager[
        Message,
        Message.Row,
        Message.Create,
        Message.Update,
        Message.Filter,
        Message.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node) -> None:
        super().__init__(source, Message)

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = Message
        _F = Message.Filter
        _FA = Message.FilterArgs

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        def select(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> AsyncIterable[_E]: ...

        @override
        async def delete_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...

        @override
        async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...


class BoundMessageManager(MessageManager, BaseBoundManager[Message]):
    def __init__(self, source: Node) -> None:
        super().__init__(source)

    def store(self, message: Message, /) -> None:
        return self._node.store(message)

    def follow(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Stream[Message]:
        from ceres.event import MessageEvent, MessageReceivedEvent

        assert self._node is not None
        filter = self._apply_default_filter(filter, kwargs)

        if TYPE_CHECKING:
            util.blackhole(MessageEvent)

        return (
            self._node.events.follow()
            .every(MessageEvent if not TYPE_CHECKING else MessageReceivedEvent)
            .map(lambda event: event.message)
            .filter(filter.matches)
        )
