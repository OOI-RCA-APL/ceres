from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...config import DatabaseConfig

_ConfigT = TypeVar("_ConfigT", bound=DatabaseConfig, covariant=True)


class DatabaseAdapter(Generic[_ConfigT], ABC):
    def __init__(self, config: _ConfigT) -> None:
        self.config = config

    @abstractmethod
    def get_engine_url(cls) -> str:
        ...

    def get_engine_config(self) -> dict[str, Any]:
        return {
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
            **(self.config.engine or {}),
        }

    def create_engine(self) -> AsyncEngine:
        return create_async_engine(
            self.get_engine_url(),
            **self.get_engine_config(),
        )
