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
    value: str | float
    color: Color
    icon: str
    description: str | None


class DisplayKind(str, Enum):
    NUMBER = "number"
    STATE = "state"
    INDICATOR = "indicator"
    GUAGE = "guage"


class BaseDisplayInfo(ImmutableDataObject):
    kind: str


class NumberDisplayInfo(ImmutableDataObject):
    kind: Literal[DisplayKind.NUMBER] = DisplayKind.NUMBER
    value: float
    unit: str | None = None
    color: Sequence[ColorStop] | Color | None = None


class StateDisplayInfo(ImmutableDataObject):
    kind: Literal[DisplayKind.STATE] = DisplayKind.STATE
    value: str | float
    options: Sequence[StateInfo]
    show_options: bool = False
    vertical_icons: bool = False


IndicatorColor = Literal["red", "yellow", "orange", "blue", "green"]
IndicatorSize = Literal["xxs", "xs", "sm", "md", "lg", "xl", "xxl"]


class IndicatorDisplayInfo(ImmutableDataObject):
    kind: Literal[DisplayKind.INDICATOR] = DisplayKind.INDICATOR
    label: str
    value: bool
    color: IndicatorColor
    size: IndicatorSize
    reversed: bool = False


class GuageDisplayInfo(ImmutableDataObject):
    kind: Literal[DisplayKind.GUAGE] = DisplayKind.GUAGE
    value: float
    unit: str | None = None
    range: RangeInfo
    color: Sequence[ColorStop] | Color | None
