from enum import Enum
from typing import Annotated, Any, Literal, Sequence

from pydantic import Field

from .data import ImmutableDataObject, Name


class LayoutKind(str, Enum):
    DISPLAY = "display"
    ROW = "row"
    COLUMN = "column"


class LayoutDisplay(ImmutableDataObject):
    kind: Literal[LayoutKind.DISPLAY] = LayoutKind.DISPLAY
    name: Name

    def __init__(self, name: Name, **kwargs: Any) -> None:
        super().__init__(**{"name": name, **kwargs})


class LayoutRow(ImmutableDataObject):
    kind: Literal[LayoutKind.ROW] = LayoutKind.ROW
    children: Sequence["LayoutNode"]

    def __init__(self, children: Sequence["LayoutNode"], **kwargs: Any) -> None:
        super().__init__(**{"children": children, **kwargs})


class LayoutColumn(ImmutableDataObject):
    kind: Literal[LayoutKind.COLUMN] = LayoutKind.COLUMN
    children: Sequence["LayoutNode"]

    def __init__(self, children: Sequence["LayoutNode"], **kwargs: Any) -> None:
        super().__init__(**{"children": children, **kwargs})


LayoutNode = Annotated[LayoutDisplay | LayoutRow | LayoutColumn, Field(discriminator="kind")]  # type: ignore


class Layout(ImmutableDataObject):
    body: LayoutNode

    def __init__(self, body: LayoutNode, **kwargs: Any) -> None:
        super().__init__(**{"body": body, **kwargs})


LayoutRow.update_forward_refs()
LayoutColumn.update_forward_refs()
