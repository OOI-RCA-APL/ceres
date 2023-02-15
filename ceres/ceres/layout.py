from enum import Enum
from typing import Annotated, Any, Callable, Literal

from pydantic import Field

from .data import DataObject, ImmutableDataObject, Name
from .internal.binding import get_bindings
from .internal.utilities import strify
from .procedure import QueryBinding


class LayoutKind(str, Enum):
    DISPLAY = "display"
    ROW = "row"
    COLUMN = "column"


class LayoutDisplay(DataObject):
    kind: Literal[LayoutKind.DISPLAY] = LayoutKind.DISPLAY
    title: str
    procedure: Name

    def __init__(self, title: str, procedure: Name | Callable[..., Any], **kwargs: Any) -> None:
        if not isinstance(procedure, str):
            bindings = get_bindings(procedure, QueryBinding)
            if not bindings:
                raise ValueError(f"function {strify(procedure)} has no query binding")

            procedure = bindings[0].name

        super().__init__(**{"title": title, "procedure": procedure, **kwargs})


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
