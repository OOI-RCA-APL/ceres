from collections.abc import Callable, Sequence
from decimal import Decimal
from enum import Enum
from textwrap import dedent
from types import MethodType
from typing import Annotated, Any, Literal, TypeAlias, TypedDict, Unpack

from pydantic import (
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

from ceres.address import Address
from ceres.component import get_component_method_binding_on
from ceres.data import Color, DataModel, Name, StrEnum


class ElementType(StrEnum):
    """Discriminator values identifying the concrete variant of an `Element`."""

    BUTTON = "button"
    ROW = "row"
    COLUMN = "column"
    CAROUSEL = "carousel"
    TEXT = "text"
    HTML = "html"
    STATE = "state"
    GAUGE = "gauge"
    CHART = "chart"
    RENDER = "render"
    DISPLAY = "display"


class Justify(StrEnum):
    """Main-axis justification for layout containers like `Row` and `Column`."""

    START = "start"
    CENTER = "center"
    END = "end"
    SPACE_BETWEEN = "space-between"
    SPACE_EVENLY = "space-evenly"


class Align(StrEnum):
    """Cross-axis alignment for layout containers like `Row` and `Column`."""

    START = "start"
    CENTER = "center"
    END = "end"


class Sizing(StrEnum):
    """Sizing behavior applied to layout containers along their main axis."""

    SHRINK = "shrink"
    GROW = "grow"


class _BaseElementArgs(TypedDict, total=False):
    css_style: str | dict[str, str] | None
    css_class: str | list[str] | None


class _BaseElement(DataModel):
    type: ElementType
    css_style: str | dict[str, str] | None = None
    css_class: str | list[str] | None = None


class Button(_BaseElement):
    """UI element that triggers a component action when clicked."""

    type: Literal[ElementType.BUTTON] = ElementType.BUTTON
    title: str
    """Label displayed on the button."""
    address: Address
    """Address of the component whose action is invoked."""
    action: Name
    """Name of the action to invoke on the target component."""
    color: Color | None = None
    """Optional color for the button, applied by the rendering frontend."""

    def __init__(
        self,
        *,
        title: str,
        address: Address | None = None,
        action: Name | Callable[..., Any],
        color: Color | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Button`.

        Args:
            title: Label displayed on the button.
            address: Address of the target component. Required unless `action` is a bound
                component method, in which case the component's system address is inferred.
            action: Either the string name of an action, or a bound component method decorated
                with an action binding. When a method is passed, its binding name and the
                containing component's address are resolved automatically.
            color: Optional display color for the button.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).

        Raises:
            ValueError: If `address` is omitted and `action` is not a bound component method,
                or if `action` is a callable without an action binding.
        """
        from ceres.component import Component

        if address is None:
            if not isinstance(action, MethodType):
                raise ValueError("address must be specified if action is not a bound method")
            elif not isinstance(action.__self__, Component):
                raise ValueError("method passed as action must be bound to a component")

            address = action.__self__.system.address

        if not isinstance(action, str):
            from ceres.component import ActionBinding

            binding = get_component_method_binding_on(action, ActionBinding)
            if not binding:
                raise ValueError(f"function {action} has no action binding")

            action = binding.name

        super().__init__(
            **{
                "title": title,
                "address": address,
                "action": action,
                "color": color,
                **kwargs,
            }
        )


class Row(_BaseElement):
    """Horizontal container that lays out its `children` left to right."""

    type: Literal[ElementType.ROW] = ElementType.ROW
    sizing: Sizing = Sizing.GROW
    """How the row sizes itself along the main axis."""
    justify: Justify = Justify.START
    """Main-axis justification for the row's children."""
    align: Align = Align.START
    """Cross-axis alignment for the row's children."""
    children: list[Element]
    """Child elements rendered inside the row."""

    def __init__(
        self,
        children: Sequence[Element],
        *,
        sizing: Sizing = Sizing.GROW,
        justify: Justify = Justify.START,
        align: Align = Align.START,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Row`.

        Args:
            children: Child elements rendered inside the row.
            sizing: How the row sizes itself along the main axis.
            justify: Main-axis justification for the row's children.
            align: Cross-axis alignment for the row's children.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "children": children,
                "sizing": sizing,
                "justify": justify,
                "align": align,
                **kwargs,
            }
        )


class Column(_BaseElement):
    """Vertical container that lays out its `children` top to bottom."""

    type: Literal[ElementType.COLUMN] = ElementType.COLUMN
    sizing: Sizing = Sizing.GROW
    """How the column sizes itself along the main axis."""
    justify: Justify = Justify.START
    """Main-axis justification for the column's children."""
    align: Align = Align.START
    """Cross-axis alignment for the column's children."""
    children: list[Element]
    """Child elements rendered inside the column."""

    def __init__(
        self,
        children: Sequence[Element],
        *,
        sizing: Sizing = Sizing.GROW,
        justify: Justify = Justify.START,
        align: Align = Align.START,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Column`.

        Args:
            children: Child elements rendered inside the column.
            sizing: How the column sizes itself along the main axis.
            justify: Main-axis justification for the column's children.
            align: Cross-axis alignment for the column's children.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "children": children,
                "sizing": sizing,
                "justify": justify,
                "align": align,
                **kwargs,
            }
        )


class Carousel(_BaseElement):
    """Scrollable container that cycles through its `children` one at a time."""

    type: Literal[ElementType.CAROUSEL] = ElementType.CAROUSEL
    height: int | str | None = None
    """Optional fixed height for the carousel, as pixels or a CSS length string."""
    children: list[Element]
    """Child elements shown as successive slides in the carousel."""

    def __init__(
        self,
        children: Sequence[Element],
        *,
        height: int | str | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Carousel`.

        Args:
            children: Child elements shown as successive slides in the carousel.
            height: Optional fixed height for the carousel, as pixels or a CSS length string.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "children": children,
                "height": height,
                **kwargs,
            }
        )


class TextVariant(StrEnum):
    """Typographic style applied to a `Text` element."""

    TITLE_1 = "title1"
    TITLE_2 = "title2"
    TITLE_3 = "title3"
    BODY_1 = "body1"
    BODY_2 = "body2"
    TH = "th"
    DESCRIPTION = "description"
    VALUE = "value"


class Text(_BaseElement):
    """Plain text element rendered with a typographic `variant` and optional color."""

    type: Literal[ElementType.TEXT] = ElementType.TEXT
    variant: TextVariant = TextVariant.BODY_2
    """Typographic style applied to the rendered text."""
    value: str
    """String shown in the UI."""
    color: Color | None = None
    """Optional text color, applied by the rendering frontend."""

    def __init__(
        self,
        value: Any,
        variant: TextVariant = TextVariant.BODY_2,
        *,
        color: Color | str | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Text` element.

        Args:
            value: Value to render, stringified by the underlying model validator.
            variant: Typographic style to apply.
            color: Optional text color, accepts a `Color` or any color string understood by
                `Color`.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "value": value,
                "variant": variant,
                "color": color,
                **kwargs,
            }
        )


class HTML(_BaseElement):
    """Element that renders a raw HTML/XML fragment, validated for well-formedness."""

    type: Literal[ElementType.HTML] = ElementType.HTML
    value: str
    """HTML or XML markup to render. Must parse as valid XML."""

    def __init__(self, value: str, **kwargs: Any) -> None:
        """Construct an `HTML` element.

        Args:
            value: HTML or XML markup to render, dedented and stripped before storage.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "value": value,
                **kwargs,
            }
        )

    @field_validator("value")
    def _validate_value(cls, value: str) -> str:
        from xml.etree import ElementTree

        try:
            ElementTree.fromstring(value)
        except SyntaxError:
            raise ValueError("must be valid HTML/XML")

        return dedent(value).strip()


AtomicValue: TypeAlias = StrictBool | StrictInt | StrictFloat | Decimal | StrictStr
"""Scalar value types accepted by UI elements that render a single data point."""


class State(_BaseElement):
    """Element that renders the current `value` using a matching entry from `options`."""

    class Option(DataModel):
        """One selectable state value and its display presentation."""

        value: AtomicValue
        """Scalar value this option matches against the `State`'s current value."""
        label: str
        """Human-readable label shown when this option is active."""
        color: Color
        """Color applied when this option is active."""
        icon: str | None = None
        """Optional icon identifier shown alongside the label."""
        description: str | None = None
        """Optional longer description shown when this option is active."""

        def __init__(
            self,
            value: AtomicValue,
            *,
            label: str,
            color: Color | str,
            icon: str | None = None,
            description: str | None = None,
            **kwargs: Any,
        ) -> None:
            """Construct a `State.Option`.

            Args:
                value: Scalar value this option represents.
                label: Human-readable label for the option.
                color: Color applied when this option is active.
                icon: Optional icon identifier.
                description: Optional longer description.
                **kwargs: Extra fields passed to the underlying model.
            """
            super().__init__(
                **{
                    "value": value,
                    "label": label,
                    "color": color,
                    "icon": icon,
                    "description": description,
                    **kwargs,
                }
            )

    type: Literal[ElementType.STATE] = ElementType.STATE
    value: AtomicValue
    """Current state value, matched against each `Option.value` to select a presentation."""
    options: list[Option]
    """Possible states and their display presentations."""

    def __init__(
        self,
        value: AtomicValue,
        options: Sequence[Option],
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `State` element.

        Args:
            value: Current state value.
            options: Possible states and their display presentations.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "value": value,
                "options": options,
                **kwargs,
            }
        )


class Gauge(_BaseElement):
    """Element that shows a numeric `value` within a `min` to `max` range."""

    class ColorStop(DataModel):
        """Breakpoint in a gauge color gradient at a given `value`."""

        value: float
        """Gauge value at which this color stop applies."""
        color: Color
        """Color applied at or above this stop."""

        def __init__(self, value: float, color: Color | str, **kwargs: Any) -> None:
            """Construct a `Gauge.ColorStop`.

            Args:
                value: Gauge value at which this color stop applies.
                color: Color applied at or above this stop.
                **kwargs: Extra fields passed to the underlying model.
            """
            super().__init__(**{"value": value, "color": color, **kwargs})

    type: Literal[ElementType.GAUGE] = ElementType.GAUGE
    value: float
    """Current value displayed on the gauge."""
    min: float
    """Lower bound of the gauge's range."""
    max: float
    """Upper bound of the gauge's range."""
    unit: str | None = None
    """Optional unit string rendered next to the value."""
    color: list[ColorStop] | Color | None = None
    """Single color, gradient defined by `ColorStop`s, or `None` for the default."""

    def __init__(
        self,
        value: float,
        min: float,
        max: float,
        *,
        unit: str | None = None,
        color: list[ColorStop] | Color | str | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Gauge`.

        Args:
            value: Current value displayed on the gauge.
            min: Lower bound of the gauge's range.
            max: Upper bound of the gauge's range.
            unit: Optional unit string rendered next to the value.
            color: Single color, gradient defined by `ColorStop`s, or a color string understood
                by `Color`.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "value": value,
                "unit": unit,
                "min": min,
                "max": max,
                "color": color,
                **kwargs,
            }
        )


class Chart(_BaseElement):
    """Element rendered as a chart from a frontend chart specification."""

    type: Literal[ElementType.CHART] = ElementType.CHART
    value: dict[str, object]
    """Chart specification, interpreted by the rendering frontend."""
    height: int | str
    """Chart height, as pixels or a CSS length string."""

    def __init__(
        self,
        value: dict[str, object],
        *,
        height: int | str,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Chart`.

        Args:
            value: Chart specification passed through to the frontend.
            height: Chart height, as pixels or a CSS length string.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "value": value,
                "height": height,
                **kwargs,
            }
        )


class PaletteColor(Color, Enum):
    """Named colors drawn from the default Ceres UI palette."""

    PRIMARY = Color("#0089ab")
    SECONDARY = Color("#26a69a")
    ACCENT = Color("#9c27b0")
    POSITIVE = Color("#21ba45")
    NEGATIVE = Color("#c10015")
    INFO = Color("#31ccec")
    WARNING = Color("#ff9d00")


class _BaseRenderer(_BaseElement):
    type: Literal[ElementType.RENDER] | Literal[ElementType.DISPLAY] = ElementType.RENDER
    title: str
    address: Address
    query: Name

    def __init__(
        self,
        *,
        address: Address | None = None,
        query: Name | Callable[..., Any],
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        from ceres.component import Component

        if address is None:
            if not isinstance(query, MethodType):
                raise ValueError("address must be specified if query is not a bound method")
            elif not isinstance(query.__self__, Component):
                raise ValueError("method passed as query must be bound to a component")

            address = query.__self__.system.address

        if not isinstance(query, str):
            from ceres.component import QueryBinding

            binding = get_component_method_binding_on(query, QueryBinding)
            if not binding:
                raise ValueError(f"function {query} has no query binding")

            query = binding.name

        super().__init__(
            **{
                "address": address,
                "query": query,
                **kwargs,
            }
        )


class Render(_BaseRenderer):
    """Element that renders the live result of a component query inline."""

    type: Literal[ElementType.RENDER] = ElementType.RENDER


class Display(_BaseRenderer):
    """Element that renders a component query result alongside a human-readable title."""

    type: Literal[ElementType.DISPLAY] = ElementType.DISPLAY
    title: str
    """Title shown above the rendered query result."""

    def __init__(
        self,
        *,
        title: str,
        address: Address | None = None,
        query: Name | Callable[..., Any],
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        """Construct a `Display`.

        Args:
            title: Title shown above the rendered query result.
            address: Address of the target component. Required unless `query` is a bound
                component method, in which case the component's system address is inferred.
            query: Either the string name of a query, or a bound component method decorated
                with a query binding.
            **kwargs: Shared base element arguments (`css_style`, `css_class`).
        """
        super().__init__(
            **{
                "title": title,
                "address": address,
                "query": query,
                **kwargs,  # type: ignore
            }
        )


type Element = Annotated[
    Button | Row | Column | Carousel | Text | HTML | State | Gauge | Chart | Render | Display,
    Field(discriminator="type"),
]
"""Discriminated union of every concrete UI element variant."""
