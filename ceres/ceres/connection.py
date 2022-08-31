from __future__ import annotations

from abc import ABC

from .component import Component


class Connection(Component, ABC):
    async def connect(self) -> bool:
        raise NotImplementedError()

    async def disconnect(self) -> None:
        raise NotImplementedError()

    async def send(self, data: str) -> None:
        raise NotImplementedError()

    async def receive(self) -> str:
        raise NotImplementedError()
