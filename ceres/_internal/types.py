from typing import TYPE_CHECKING, Sequence, TypeAlias, TypeVar

_T = TypeVar("_T")

if TYPE_CHECKING:
    MaybeSequence = Sequence[_T] | _T
else:
    MaybeSequence: TypeAlias = _T | list[_T]
