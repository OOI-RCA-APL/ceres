from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
    Filtering,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.models.messages import (
    MessageCreate,
    MessageData,
    MessageDirection,
    MessageDirectionInput,
    MessageDirectionRaw,
    MessageField,
    MessageFilter,
    MessageFilterArgs,
    MessageOrder,
    MessageUpdate,
)
from ceres.__internal__.record import BaseRecord

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource, NodeSource

__all__ = [
    "Message",
    "MessageDirectionInput",
    "MessageDirectionRaw",
]


class _BaseMessageQuery(
    BaseEntityQuery[
        "Message",
        MessageFilter,
        MessageUpdate,
        "MessageQuery",
    ]
):
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[MessageQuery]:
        return MessageQuery

    @override
    def where(  # type: ignore
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> MessageQuery:
        return super().where(filter, **kwargs)


class MessageQuery(
    EntityQuery[
        "Message",
        MessageFilter,
        MessageUpdate,
    ],
    _BaseMessageQuery,
):
    """Query builder for `Message` records."""

    __slots__ = ()


class MessageManager(
    BaseEntityManager[
        "Message",
        MessageCreate,
        MessageUpdate,
        MessageFilter,
        MessageFilterArgs,
    ],
    _BaseMessageQuery,
):
    """Database-bound manager for `Message` records."""

    __slots__ = ()

    def __init__(
        self,
        source: DatabaseSource,
        /,
        filtering: Filtering[MessageFilter] = None,
    ) -> None:
        super().__init__(source, Message, filtering)

    async def get(self, id: UUID, /) -> Message | None:
        """Fetch a single message by its identifier.

        Args:
            id: UUID of the message to fetch.

        Returns:
            The matching message, or `None` if no message with that id exists.
        """
        return await self.where(id=id).first()


class BoundMessageManager(MessageManager, BaseNodeManager):
    """Node-bound message manager that exposes the live event stream as messages."""

    __slots__ = ()

    def __init__(
        self,
        source: NodeSource,
        /,
        filtering: Filtering[MessageFilter] = None,
    ) -> None:
        super().__init__(source, filtering)

    @property
    def stream(self) -> MessageOutputChannel:
        """Return an output channel that yields messages from sent and received events."""
        from ceres.event import MessageReceivedEvent, MessageSentEvent

        return MessageOutputChannel(
            self.__node__.events.stream.every(MessageSentEvent, MessageReceivedEvent)
            .map(lambda event: event.message)
            .where(lambda message: self._get_resolved_filter().matches(message))
        )


class MessageOutputChannel(
    EntityOutputChannel[
        "Message",
        MessageFilter,
        MessageFilterArgs,
    ]
):
    """Output channel for streaming `Message` instances with filtering helpers."""

    __slots__ = ()

    @override
    def _get_filter_class(self) -> type[MessageFilter]:
        return MessageFilter

    @property
    def received(self) -> MessageOutputChannel:
        """Return a new channel filtered to inbound messages only."""
        return self.where(lambda message: message.direction == MessageDirection.RECEIVE)

    @property
    def sent(self) -> MessageOutputChannel:
        """Return a new channel filtered to outbound messages only."""
        return self.where(lambda message: message.direction == MessageDirection.SEND)

    @override
    def where(  # type: ignore
        self,
        filter: MessageFilter | Callable[[Message], bool] | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> MessageOutputChannel:
        """Return a new channel that only yields messages matching the given filter.

        Args:
            filter: A `MessageFilter`, a callable predicate, or `None` to filter by keyword
                arguments only.
            **kwargs: Additional filter fields forwarded to `MessageFilter`.

        Returns:
            A filtered `MessageOutputChannel`.
        """
        return super().where(filter, **kwargs)


class Message(
    BaseRecord,
    MessageCreate,
    ConcreteEntity,
    slots=True,
):
    """A chunk of data sent or received on a connection.

    Each `Message` captures the raw bytes that flowed across a connection along with metadata
    identifying which connection produced it and which direction it traveled. Messages are the
    raw input from which `Particle` instances are typically parsed.
    """

    Manager = MessageManager
    BoundManager = BoundMessageManager
    Create = MessageCreate
    Update = MessageUpdate
    Filter = MessageFilter
    FilterArgs = MessageFilterArgs
    Field = MessageField
    Order = MessageOrder
    Direction = MessageDirection
    Data = MessageData

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("message")
