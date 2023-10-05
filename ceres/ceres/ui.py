from abc import ABC
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Callable, Literal, Mapping, Sequence, TypeAlias

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from typing_extensions import Unpack

from ceres.data import Color, DataObject, ImmutableDataObject, Name
from ceres.internal.utilities import StrEnum, strify


class ElementType(StrEnum):
    BUTTON = "button"
    ROW = "row"
    COLUMN = "column"
    CAROUSEL = "carousel"
    VALUE = "value"
    STATE = "state"
    GAUGE = "gauge"
    CHART = "chart"
    DISPLAY = "display"


class Justify(StrEnum):
    START = "start"
    CENTER = "center"
    END = "end"
    SPACE_BETWEEN = "space-between"
    SPACE_EVENLY = "space-evenly"


class Align(StrEnum):
    START = "start"
    CENTER = "center"
    END = "end"


class Sizing(StrEnum):
    SHRINK = "shrink"
    GROW = "grow"


_element_classes: list[type[DataObject]] = []


def __update_forward_refs() -> None:
    for current in _element_classes:
        current.model_rebuild()


class _BaseElement(DataObject, ABC):
    def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]):
        super().__init_subclass__(**kwargs)
        _element_classes.append(cls)
        return cls


class Button(_BaseElement):
    type: Literal[ElementType.BUTTON] = ElementType.BUTTON
    title: str
    action: Name
    color: Color | None = None

    def __init__(
        self,
        *,
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


class Row(_BaseElement):
    type: Literal[ElementType.ROW] = ElementType.ROW
    sizing: Sizing = Sizing.SHRINK
    justify: Justify = Justify.START
    align: Align = Align.START
    children: list["Element"]


class Column(_BaseElement):
    type: Literal[ElementType.COLUMN] = ElementType.COLUMN
    justify: Justify = Justify.START
    align: Align = Align.START
    children: list["Element"]


class Carousel(_BaseElement):
    type: Literal[ElementType.CAROUSEL] = ElementType.CAROUSEL
    height: int | str | None = None
    children: list["Element"]


AtomicValue: TypeAlias = StrictBool | StrictInt | StrictFloat | Decimal | StrictStr


class Value(_BaseElement):
    type: Literal[ElementType.VALUE] = ElementType.VALUE
    value: AtomicValue
    unit: str | None = None
    color: Color | None = None


class State(_BaseElement):
    class Option(ImmutableDataObject):
        value: AtomicValue
        label: str
        color: Color
        icon: str | None = None
        description: str | None = None

    type: Literal[ElementType.STATE] = ElementType.STATE
    value: AtomicValue
    options: Sequence[Option]


class Gauge(_BaseElement):
    class ColorStop(ImmutableDataObject):
        value: float
        color: Color

    type: Literal[ElementType.GAUGE] = ElementType.GAUGE
    value: float
    unit: str | None = None
    min: float
    max: float
    color: Sequence[ColorStop] | Color | None = None


class Chart(_BaseElement):
    type: Literal[ElementType.CHART] = ElementType.CHART
    value: Mapping[str, object]
    height: int


class PaletteColor(Color, Enum):
    PRIMARY = Color("#0089ab")
    SECONDARY = Color("#26a69a")
    ACCENT = Color("#9c27b0")
    DARK = Color("#1d1d1d")
    POSITIVE = Color("#21ba45")
    NEGATIVE = Color("#c10015")
    INFO = Color("#31ccec")
    WARNING = Color("#f2c037")


class Display(_BaseElement):
    type: Literal[ElementType.DISPLAY] = ElementType.DISPLAY
    title: str
    source: Name

    def __init__(self, *, title: str, source: Name | Callable[..., Any], **kwargs: Any) -> None:
        if not isinstance(source, str):
            from ceres.component import QueryBinding, get_method_binding

            binding = get_method_binding(source, QueryBinding)
            if not binding:
                raise ValueError(f"function {strify(source)} has no query binding")

            source = binding.name

        super().__init__(**{"title": title, "source": source, **kwargs})


Element = Annotated[  # type: ignore
    Button | Row | Column | Carousel | Value | State | Gauge | Chart | Display,
    Field(discriminator="type"),
]


__update_forward_refs()
