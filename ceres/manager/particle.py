from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterable, Unpack, override

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres.particle import Particle, ParticleFilter, ParticleFilterArgs

with lazy_imports(__name__):
    from ceres._internal import util
    from ceres.database import Database
    from ceres.node import Node
    from ceres.stream import Stream


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

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = Particle
        _F = Particle.Filter
        _FA = Particle.FilterArgs

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


class BoundParticleManager(ParticleManager, BaseBoundManager[Particle]):
    def __init__(self, source: Node) -> None:
        super().__init__(source)

    def store(self, particle: Particle, /) -> None:
        return self._node.store(particle)

    def follow(
        self,
        filter: ParticleFilter | None = None,
        **kwargs: Unpack[ParticleFilterArgs],
    ) -> Stream[Particle]:
        from ceres.event import ParticleEvent

        assert self._node is not None
        filter = self._apply_default_filter(filter, kwargs)

        if TYPE_CHECKING:
            util.blackhole(ParticleEvent)

        return (
            self._node.events.follow()
            .every(ParticleEvent)
            .map(lambda event: event.particle)
            .filter(filter.matches)
        )
