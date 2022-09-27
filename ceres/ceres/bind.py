from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar, overload

from pydantic import BaseModel

from .component import ContextT
from .protocols import BoundConnection

if TYPE_CHECKING:
    from .component import Component

Bindable = BoundConnection
MethodT = TypeVar("MethodT", bound=Callable[[Any], BoundConnection])
InstanceT = TypeVar("InstanceT", bound=object)
ValueT = TypeVar("ValueT")


class BindInfo(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    name: str
    cls: type[Bindable]


class ConnectionDescriptor:
    def __init__(self, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, component: None, owner: Any) -> ConnectionDescriptor:
        ...

    @overload
    def __get__(self, component: Component[ContextT], owner: Any) -> BoundConnection:
        ...

    def __get__(
        self,
        component: Component[ContextT] | None,
        owner: Any,
    ) -> ConnectionDescriptor | BoundConnection:
        if component is None:
            return self

        if connection := component.context.unit.get_connection(self.name):
            return connection

        raise ValueError(f"no connection in unit named '{self.name}'")


def connection(
    name: str | None = None,
) -> Callable[[MethodT], ConnectionDescriptor]:
    def inner(function: MethodT) -> ConnectionDescriptor:
        return ConnectionDescriptor(name or function.__name__)

    return inner
