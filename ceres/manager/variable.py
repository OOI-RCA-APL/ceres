from __future__ import annotations

from typing import TYPE_CHECKING, Any, Unpack, overload, override

from pydantic import ValidationError

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres._internal.util import get_type_adapter
from ceres.address import Address
from ceres.event import VariableAssignedEvent
from ceres.stream import Stream
from ceres.variable import Variable

with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.node import Node


class VariableManager(
    BaseEntityManager[
        Variable,
        Variable.Row,
        Variable.Create,
        Variable.Update,
        Variable.Filter,
        Variable.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node) -> None:
        super().__init__(source, Variable)


class BoundVariableManager(VariableManager, BaseBoundManager[Variable]):
    def __init__(self, source: Node) -> None:
        super().__init__(source)

    def store(self, variable: Variable, /) -> None:
        return self._node.store(variable)

    def assign(self, name: str, value: Any) -> Variable:
        variable = Variable(
            address=self._node.address,
            name=name,
            value=value,
        )

        self.store(variable)
        self._node.events.emit(VariableAssignedEvent, variable=variable)
        return variable

    @overload
    async def read(
        self,
        name: str,
        parse: None = None,
        default: None = None,
        *,
        address: Address | None = None,
    ) -> Any | None: ...

    @overload
    async def read(
        self,
        name: str,
        parse: None,
        default: Any,
        *,
        address: Address | None = None,
    ) -> Any: ...

    @overload
    async def read[
        T, D
    ](self, name: str, parse: type[T], default: D, *, address: Address | None = None) -> T | D: ...

    async def read(
        self,
        name: str,
        parse: type | None = None,
        default: Any = None,
        *,
        address: Address | None = None,
    ) -> Any | None:
        variable = await self.get(address=address or self._node.address, name=name)
        if variable is None:
            return default

        if parse is not None:
            try:
                return get_type_adapter(parse).validate_python(variable.value)
            except ValidationError:
                return default

        return variable.value

    def follow(
        self,
        filter: Variable.Filter | None = None,
        **kwargs: Unpack[Variable.FilterArgs],
    ) -> Stream[Variable]:
        filter = self._apply_default_filter(filter, kwargs)
        return (
            self._node.events.follow()
            .every(VariableAssignedEvent)
            .map(lambda event: event.variable)
            .filter(filter.matches)
        )

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = Variable

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, /, **kwargs: Unpack[_E.FilterArgs]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, /, **kwargs: Unpack[_E.FilterArgs]
        ) -> _E | None: ...

        @override
        async def delete_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, **kwargs: Unpack[_E.FilterArgs]
        ) -> int: ...

        @override
        async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, /, **kwargs: Unpack[_E.FilterArgs]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, /, **kwargs: Unpack[_E.FilterArgs]
        ) -> int: ...
