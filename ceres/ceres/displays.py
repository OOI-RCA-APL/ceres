from enum import Enum
from typing import Literal, Sequence

from pydantic.color import Color as Color

from .data import ImmutableDataObject


class ColorStop(ImmutableDataObject):
    value: float
    color: Color


class RangeInfo(ImmutableDataObject):
    min: float
    max: float


class StateInfo(ImmutableDataObject):
    value: bool | int | float | str
    label: str
    color: Color
    icon: str | None = None
    description: str | None = None


class DisplayKind(str, Enum):
    NUMBER = "number"
    STATE = "state"
    INDICATOR = "indicator"
    GUAGE = "guage"


class BaseDisplay(ImmutableDataObject):
    kind: str


class NumberDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.NUMBER] = DisplayKind.NUMBER
    value: float
    unit: str | None = None
    color: Sequence[ColorStop] | Color | None = None


class StateDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.STATE] = DisplayKind.STATE
    value: bool | int | float | str
    options: Sequence[StateInfo]
    show_options: bool = False
    vertical_icons: bool = False


IndicatorColor = Literal["red", "yellow", "orange", "blue", "green"]
IndicatorSize = Literal["xxs", "xs", "sm", "md", "lg", "xl", "xxl"]


class IndicatorDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.INDICATOR] = DisplayKind.INDICATOR
    label: str
    value: bool
    color: IndicatorColor
    size: IndicatorSize
    reversed: bool = False


class GuageDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.GUAGE] = DisplayKind.GUAGE
    value: float
    unit: str | None = None
    range: RangeInfo
    color: Sequence[ColorStop] | Color | None
