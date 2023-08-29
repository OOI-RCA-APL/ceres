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


class DisplayKind(StrEnum):
    VALUE = "value"
    STATE = "state"
    GAUGE = "gauge"
    CHART = "chart"


class BaseDisplay(ImmutableDataObject):
    kind: DisplayKind


class ValueDisplay(BaseDisplay):
    kind: Literal[DisplayKind.VALUE] = DisplayKind.VALUE
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

    kind: Literal[DisplayKind.STATE] = DisplayKind.STATE
    value: AtomicValue
    options: Sequence[Option]


class GaugeDisplay(BaseDisplay):
    class ColorStop(ImmutableDataObject):
        value: float
        color: Color

    kind: Literal[DisplayKind.GAUGE] = DisplayKind.GAUGE
    value: float
    unit: str | None = None
    min: float
    max: float
    color: Sequence[ColorStop] | Color | None = None


class ChartDisplay(BaseDisplay):
    kind: Literal[DisplayKind.CHART] = DisplayKind.CHART
    value: Mapping[str, object]
    height: int


Display = ValueDisplay | StateDisplay | GaugeDisplay | ChartDisplay
