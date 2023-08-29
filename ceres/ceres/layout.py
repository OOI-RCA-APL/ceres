from typing import Annotated, Any, Callable, Literal

from pydantic import Field

from ceres.data import Color, DataObject, ImmutableDataObject, Name
from ceres.internal.utilities import StrEnum, strify


class LayoutKind(StrEnum):
    DISPLAY = "display"
    BUTTON = "button"
    ROW = "row"
    COLUMN = "column"
    CAROUSEL = "carousel"


class LayoutDisplay(DataObject):
    kind: Literal[LayoutKind.DISPLAY] = LayoutKind.DISPLAY
    title: str
    query: Name

    def __init__(self, title: str, query: Name | Callable[..., Any], **kwargs: Any) -> None:
        if not isinstance(query, str):
            from ceres.component import QueryBinding, get_method_binding

            binding = get_method_binding(query, QueryBinding)
            if not binding:
                raise ValueError(f"function {strify(query)} has no query binding")

            query = binding.name

        super().__init__(**{"title": title, "query": query, **kwargs})


class LayoutButton(DataObject):
    kind: Literal[LayoutKind.BUTTON] = LayoutKind.BUTTON
    title: str
    action: Name
    color: Color | None = None

    def __init__(
        self,
        title: str,
        action: Name | Callable[..., Any],
        color: Color | None = None,
        **kwargs: Any,
    ) -> None:
        if not isinstance(action, str):
            from ceres.component import ActionBinding, get_method_binding

            binding = get_method_binding(action, ActionBinding)
            if not binding:
                raise ValueError(f"function {strify(action)} has no action binding")

            action = binding.name

        super().__init__(
            **{
                "title": title,
                "action": action,
                "color": color,
                **kwargs,
            }
        )


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
    LayoutDisplay | LayoutButton | LayoutRow | LayoutColumn | LayoutCarousel,
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


def __update_forward_refs() -> None:
    for current in [LayoutDisplay, LayoutButton, LayoutRow, LayoutColumn, LayoutCarousel]:
        current.model_rebuild()


__update_forward_refs()
