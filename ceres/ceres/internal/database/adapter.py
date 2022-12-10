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

    @abstractmethod
    def get_engine_config(self) -> dict[str, Any]:
        ...

    def create_engine(self) -> AsyncEngine:
        return create_async_engine(
            self.get_engine_url(),
            **self.get_engine_config(),
        )
