from typing import TYPE_CHECKING

from typing_extensions import Unpack

from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres._internal.typedecs import __Database__, __Node__
from ceres._internal.utilities import blackhole
from ceres.event import MessageEvent, MessageReceivedEvent
from ceres.message import Message
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
    def __init__(self, source: __Database__ | __Node__) -> None:
        super().__init__(source, Message)


class LiveMessageManager(MessageManager, BaseBoundManager[Message]):
    def __init__(self, source: __Node__) -> None:
        super().__init__(source)

    def store(self, message: Message, /) -> None:
        return self._node.store(message)

    def follow(
        self,
        filter: Message.Filter | None = None,
        **kwargs: Unpack[Message.FilterArgs],
    ) -> Stream[Message]:
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
