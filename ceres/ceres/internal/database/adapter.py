from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...config import DatabaseConfig

_ConfigT = TypeVar("_ConfigT", bound=DatabaseConfig, covariant=True)


class DatabaseAdapter(Generic[_ConfigT], ABC):
    def __init__(self, id: UUID, config: _ConfigT) -> None:
        self.__id = id
        self.__config = config

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def config(self) -> _ConfigT:
        return self.__config

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
