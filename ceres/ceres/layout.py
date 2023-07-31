from enum import Enum
from typing import Annotated, Any, Callable, Literal

from pydantic import Field

from ceres.data import DataObject, ImmutableDataObject, Name
from ceres.component import get_function_bindings
from ceres.internal.utilities import strify
from ceres.component import QueryBinding


class LayoutKind(str, Enum):
    DISPLAY = "display"
    ROW = "row"
    COLUMN = "column"
    CAROUSEL = "carousel"


class LayoutDisplay(DataObject):
    kind: Literal[LayoutKind.DISPLAY] = LayoutKind.DISPLAY
    title: str
    query: Name

    def __init__(self, title: str, query: Name | Callable[..., Any], **kwargs: Any) -> None:
        if not isinstance(query, str):
            bindings = get_function_bindings(query, QueryBinding)
            if not bindings:
                raise ValueError(f"function {strify(query)} has no query binding")

            query = bindings[0].name

        super().__init__(**{"title": title, "query": query, **kwargs})


class LayoutRow(DataObject):
    kind: Literal[LayoutKind.ROW] = LayoutKind.ROW
    children: list["LayoutNode"]

    def __init__(self, children: list["LayoutNode"], **kwargs: Any) -> None:
        super().__init__(**{"children": children, **kwargs})


class LayoutColumn(DataObject):
    kind: Literal[LayoutKind.COLUMN] = LayoutKind.COLUMN
    children: list["LayoutNode"]

    def __init__(self, children: list["LayoutNode"], **kwargs: Any) -> None:
        super().__init__(**{"children": children, **kwargs})


class LayoutCarousel(DataObject):
    kind: Literal[LayoutKind.CAROUSEL] = LayoutKind.CAROUSEL
    children: list["LayoutNode"]
    height: int | str | None = None

    def __init__(
        self,
        children: list["LayoutNode"],
        *,
        height: str | int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            **{
                "children": children,
                "height": height,
                **kwargs,
            }
        )


LayoutNode = Annotated[  # type: ignore
    LayoutDisplay | LayoutRow | LayoutColumn | LayoutCarousel,
    Field(discriminator="kind"),
]
LayoutContainerNode = Annotated[
    LayoutRow | LayoutColumn | LayoutCarousel,
    Field(discriminator="kind"),
]


class Layout(ImmutableDataObject):
    body: LayoutContainerNode

    def __init__(self, body: LayoutNode, **kwargs: Any) -> None:
        super().__init__(**{"body": body, **kwargs})


def _update_forward_refs() -> None:
    for _current in [LayoutDisplay, LayoutRow, LayoutColumn, LayoutCarousel]:
        _current.update_forward_refs()


_update_forward_refs()
