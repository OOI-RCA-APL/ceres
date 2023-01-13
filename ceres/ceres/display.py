from enum import Enum
from typing import Literal, Mapping, Sequence, TypeAlias

from pydantic.color import Color as Color

from .data import ImmutableDataObject

AtomicValue: TypeAlias = str | int | float | bool


class DisplayKind(str, Enum):
    VALUE = "value"
    STATE = "state"
    GAUGE = "gauge"
    CHART = "chart"


class BaseDisplay(ImmutableDataObject):
    kind: str


class ValueDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.VALUE] = DisplayKind.VALUE
    value: AtomicValue
    unit: str | None = None
    color: Color | None = None


class StateInfo(ImmutableDataObject):
    value: AtomicValue
    label: str
    color: Color
    icon: str | None = None
    description: str | None = None


class StateDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.STATE] = DisplayKind.STATE
    value: AtomicValue
    options: Sequence[StateInfo]


class RangeInfo(ImmutableDataObject):
    min: float
    max: float


class ColorStop(ImmutableDataObject):
    value: float
    color: Color


class GaugeDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.GAUGE] = DisplayKind.GAUGE
    value: float
    unit: str | None = None
    range: RangeInfo
    color: Sequence[ColorStop] | Color | None = None


class ChartDisplay(ImmutableDataObject):
    kind: Literal[DisplayKind.CHART] = DisplayKind.CHART
    value: Mapping[str, object]
    height: int
