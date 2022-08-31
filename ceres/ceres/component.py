from __future__ import annotations

from abc import ABC
from typing import Generic, TypeVar

from pydantic import BaseModel

from .exceptions import ComponentNotSetupException


class ComponentContext(BaseModel, ABC):
    pass


ContextT = TypeVar("ContextT", bound=ComponentContext)


class Component(Generic[ContextT], ABC):
    def __init__(self) -> None:
        self.__context__: ContextT | None = None

    def setup(self, context: ContextT) -> None:
        self.__context__ = context

    @property
    def context(self) -> ContextT:
        if not self.__context__:
            raise ComponentNotSetupException(
                "Attempted to access component context before setup() is called."
            )

        return self.__context__
