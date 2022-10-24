from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from sqlalchemy import Engine as SyncEngine
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...config import DatabaseConfig

ConfigT = TypeVar("ConfigT", bound=DatabaseConfig)


class DatabaseAdapter(Generic[ConfigT], ABC):
    def __init__(self, config: ConfigT) -> None:
        self.config = config

    def create_async_engine(self) -> AsyncEngine:
        return create_async_engine(
            self.get_async_engine_url(),
            **self.get_engine_config(),
        )

    def create_sync_engine(self) -> SyncEngine:
        return create_sync_engine(
            self.get_sync_engine_url(),
            **self.get_engine_config(),
        )

    @abstractmethod
    def get_async_engine_url(cls) -> str:
        ...

    @abstractmethod
    def get_sync_engine_url(cls) -> str:
        ...

    @abstractmethod
    def get_engine_config(cls) -> dict[str, Any]:
        ...
