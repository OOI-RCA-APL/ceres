from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import Field

from .data import DataObject, ImmutableDataObject, Name


class LayoutKind(str, Enum):
    DISPLAY = "display"
    ROW = "row"
    COLUMN = "column"


class LayoutDisplay(DataObject):
    kind: Literal[LayoutKind.DISPLAY] = LayoutKind.DISPLAY
    name: Name

    def __init__(self, name: Name, **kwargs: Any) -> None:
        super().__init__(**{"name": name, **kwargs})


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


LayoutNode = Annotated[LayoutDisplay | LayoutRow | LayoutColumn, Field(discriminator="kind")]  # type: ignore
LayoutContainerNode = Annotated[LayoutRow | LayoutColumn, Field(discriminator="kind")]  # type: ignore


class Layout(ImmutableDataObject):
    body: LayoutContainerNode

    def __init__(self, body: LayoutNode, **kwargs: Any) -> None:
        super().__init__(**{"body": body, **kwargs})


LayoutRow.update_forward_refs()
LayoutColumn.update_forward_refs()
