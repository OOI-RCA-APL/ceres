from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import Unpack

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres.message import Message

with lazy_imports(__name__):
    from ceres._internal.utilities import blackhole
    from ceres.database.database import Database
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


class LiveMessageManager(MessageManager, BaseBoundManager[Message]):
    def __init__(self, source: Node) -> None:
        super().__init__(source)

    def store(self, message: Message, /) -> None:
        return self._node.store(message)

    def follow(
        self,
        filter: Message.Filter | None = None,
        **kwargs: Unpack[Message.FilterArgs],
    ) -> Stream[Message]:
        from ceres.event import MessageEvent, MessageReceivedEvent

        assert self._node is not None
        filter = self._apply_default_filter(filter, kwargs)

        if TYPE_CHECKING:
            blackhole(MessageEvent)

        return (
            self._node.events.follow()
            .every(MessageEvent if not TYPE_CHECKING else MessageReceivedEvent)
            .map(lambda event: event.message)
            .filter(filter.matches)
        )
