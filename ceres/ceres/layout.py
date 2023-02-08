from enum import Enum
from typing import Annotated, Literal, Sequence

from pydantic import Field

from .data import ImmutableDataObject, Name


class LayoutKind(str, Enum):
    DISPLAY = "display"
    ROW = "row"
    COLUMN = "column"


class LayoutDisplay(ImmutableDataObject):
    kind: Literal[LayoutKind.DISPLAY] = LayoutKind.DISPLAY
    name: Name


class LayoutRow(ImmutableDataObject):
    kind: Literal[LayoutKind.ROW] = LayoutKind.ROW
    children: Sequence["LayoutNode"]


class LayoutColumn(ImmutableDataObject):
    kind: Literal[LayoutKind.COLUMN] = LayoutKind.COLUMN
    children: Sequence["LayoutNode"]


LayoutNode = Annotated[LayoutDisplay | LayoutRow | LayoutColumn, Field(discriminator="kind")]  # type: ignore


class Layout(ImmutableDataObject):
    body: LayoutNode


LayoutRow.update_forward_refs()
LayoutColumn.update_forward_refs()
