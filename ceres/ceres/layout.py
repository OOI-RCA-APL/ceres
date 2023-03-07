from enum import Enum
from typing import Annotated, Any, Callable, Literal

from pydantic import Field

from ceres.data import DataObject, ImmutableDataObject, Name
from ceres.internal.binding import get_function_bindings
from ceres.internal.utilities import strify
from ceres.procedure import QueryBinding


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
            bindings = get_function_bindings(procedure, QueryBinding)
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


LayoutNode = Annotated[  # type: ignore
    LayoutDisplay | LayoutRow | LayoutColumn,
    Field(discriminator="kind"),
]
LayoutContainerNode = Annotated[
    LayoutRow | LayoutColumn,
    Field(discriminator="kind"),
]


class Layout(ImmutableDataObject):
    body: LayoutContainerNode

    def __init__(self, body: LayoutNode, **kwargs: Any) -> None:
        super().__init__(**{"body": body, **kwargs})


LayoutRow.update_forward_refs()
LayoutColumn.update_forward_refs()
