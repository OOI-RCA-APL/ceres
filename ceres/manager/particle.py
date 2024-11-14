from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterable, Unpack, cast, override

from typing_extensions import TypeVar

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres.particle import (
    DynamicParticleData,
    Particle,
    ParticleFilter,
    ParticleFilterArgs,
    ParticleUpdate,
)

with lazy_imports(__name__):
    from ceres._internal import util
    from ceres.database import Database
    from ceres.node import Node
    from ceres.stream import Stream

_E = Particle
_F = ParticleFilter
_FA = ParticleFilterArgs
if TYPE_CHECKING:
    _T = TypeVar("_T", bound=DynamicParticleData, default=DynamicParticleData)
else:
    _T = TypeVar("_T", default=DynamicParticleData)


class ParticleManager(
    BaseEntityManager[
        Particle,
        Particle.Row,
        Particle.Create,
        Particle.Update,
        Particle.Filter,
        Particle.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node) -> None:
        super().__init__(source, Particle)

    def __convert_or_none(
        self,
        particle: Particle | None,
        cls: type[_T] | None,
    ) -> Particle[_T] | None:
        if particle is None:
            return None

        if cls is None:
            return particle  # type: ignore

        try:
            return particle.convert_or_none(cls)
        except ValueError:
            return None

    def __get_cls(self, filter: _F[_T] | None, filter_kwargs: _FA[_T] | None) -> type[_T] | None:
        cls = filter_kwargs.get("cls") if filter_kwargs is not None else None
        if cls is None:
            if filter is not None:
                cls = filter.cls
        return cls

    @override
    async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        filter: _F[_T] | None = None,
        **kwargs: Unpack[_FA[_T]],
    ) -> list[_E[_T]]:
        particles = await super().get_all(filter, **kwargs)
        cls = self.__get_cls(filter, kwargs)
        output: list[_E[_T]] = []
        for particle in particles:
            converted = self.__convert_or_none(particle, cls)
            if converted is not None:
                output.append(converted)

        return output

    @override
    async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        filter: _F[_T] | None = None,
        **kwargs: Unpack[_FA[_T]],
    ) -> _E[_T] | None:
        particle = await super().get(filter, **kwargs)
        cls = self.__get_cls(filter, kwargs)
        return self.__convert_or_none(particle, cls)

    @override
    async def select(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        filter: _F[_T] | None = None,
        **kwargs: Unpack[_FA[_T]],
    ) -> AsyncIterable[_E[_T]]:
        cls = self.__get_cls(filter, kwargs)
        async for particle in super().select(filter, **kwargs):
            converted = self.__convert_or_none(particle, cls)
            if converted is not None:
                yield converted

    @override
    async def update(self, filter: _F[_T], assign: ParticleUpdate) -> _E[_T] | None:
        particle = await super().update(filter, assign)
        return self.__convert_or_none(particle, filter.cls)

    @override
    async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        filter: _F[_T] | None = None,
        **kwargs: Unpack[_FA[_T]],
    ) -> _E[_T] | None:
        particle = await super().delete(filter, **kwargs)
        cls = self.__get_cls(filter, kwargs)
        return self.__convert_or_none(particle, cls)


class BoundParticleManager(ParticleManager, BaseBoundManager[Particle]):
    def __init__(self, source: Node) -> None:
        super().__init__(source)

    def store(self, particle: Particle, /) -> None:
        return self._node.store(particle)

    def follow(
        self,
        filter: ParticleFilter[_T] | None = None,
        **kwargs: Unpack[ParticleFilterArgs[_T]],
    ) -> Stream[Particle[_T]]:
        from ceres.event import ParticleEvent

        assert self._node is not None
        filter = self._apply_default_filter(filter, kwargs)  # type: ignore
        assert filter is not None

        if TYPE_CHECKING:
            util.blackhole(ParticleEvent)

        result = (
            self._node.events.follow()
            .every(ParticleEvent)
            .map(lambda event: event.particle)
            .filter(filter.matches)
        )

        return cast(Stream[Particle[_T]], result)
