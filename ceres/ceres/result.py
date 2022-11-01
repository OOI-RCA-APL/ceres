from dataclasses import field
from typing import TYPE_CHECKING, Generic, Literal, TypeVar, final

from pydantic.dataclasses import dataclass as validated_dataclass

ValueT = TypeVar("ValueT")
ErrorT = TypeVar("ErrorT")


@final
@validated_dataclass(frozen=True)
class Ok(Generic[ValueT, ErrorT]):
    value: ValueT
    ok: Literal[True] = field(default=True, init=False)

    if TYPE_CHECKING:
        __match_args__: tuple[Literal["value"], Literal["ok"]] = ("value", "ok")

    def __str__(self) -> str:
        return f"Ok({self.value})"

    def __bool__(self) -> bool:
        return True


@final
@validated_dataclass(frozen=True)
class Fail(Generic[ValueT, ErrorT]):
    error: ErrorT
    ok: Literal[False] = field(default=False, init=False)

    if TYPE_CHECKING:
        __match_args__: tuple[Literal["error"], Literal["ok"]] = ("error", "ok")

    def __str__(self) -> str:
        return f"Fail({self.error})"

    def __bool__(self) -> bool:
        return False


Result = Ok[ValueT, ErrorT] | Fail[ValueT, ErrorT]
