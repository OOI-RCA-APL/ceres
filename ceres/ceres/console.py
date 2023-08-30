from decimal import Decimal
from enum import Enum
from typing import Literal, Mapping, Sequence, TypeAlias

from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr

from ceres.data import Color, ImmutableDataObject
from ceres.internal.utilities import StrEnum


class ConsoleColor(Color, Enum):
    PRIMARY = Color("#0089ab")
    SECONDARY = Color("#26a69a")
    ACCENT = Color("#9c27b0")
    DARK = Color("#1d1d1d")
    POSITIVE = Color("#21ba45")
    NEGATIVE = Color("#c10015")
    INFO = Color("#31ccec")
    WARNING = Color("#f2c037")


AtomicValue: TypeAlias = StrictBool | StrictInt | StrictFloat | Decimal | StrictStr


class DisplayType(StrEnum):
    VALUE = "value"
    STATE = "state"
    GAUGE = "gauge"
    CHART = "chart"


class BaseDisplay(ImmutableDataObject):
    type: DisplayType


class ValueDisplay(BaseDisplay):
    type: Literal[DisplayType.VALUE] = DisplayType.VALUE
    value: AtomicValue
    unit: str | None = None
    color: Color | None = None


class StateDisplay(BaseDisplay):
    class Option(ImmutableDataObject):
        value: AtomicValue
        label: str
        color: Color
        icon: str | None = None
        description: str | None = None

    type: Literal[DisplayType.STATE] = DisplayType.STATE
    value: AtomicValue
    options: Sequence[Option]


class GaugeDisplay(BaseDisplay):
    class ColorStop(ImmutableDataObject):
        value: float
        color: Color

    type: Literal[DisplayType.GAUGE] = DisplayType.GAUGE
    value: float
    unit: str | None = None
    min: float
    max: float
    color: Sequence[ColorStop] | Color | None = None


class ChartDisplay(BaseDisplay):
    type: Literal[DisplayType.CHART] = DisplayType.CHART
    value: Mapping[str, object]
    height: int


Display = ValueDisplay | StateDisplay | GaugeDisplay | ChartDisplay
