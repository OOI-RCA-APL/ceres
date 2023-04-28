import json
from datetime import datetime
from typing import TypeVar

from typing_extensions import Self

from ceres import Message, MessageDirection, ParseException, Parser
from ceres.data import DataObject, ImmutableDataObject


class DoesNotExistParseException(ParseException):
    pass


class InvalidValueParseException(ParseException):
    pass


def _host_does_not_exist_error(
    content: bytes,
    key: bytes,
    subkey: bytes | int | None,
    message: str,
) -> DoesNotExistParseException:
    key_text = "[" + json.dumps(key) + "]"
    subkey_text = "[" + json.dumps(subkey) + "]" if subkey is not None else ""

    message = f"Key {key_text}{subkey_text} {message} in message {json.dumps(content)}."
    raise DoesNotExistParseException(message)


def _host_invalid_value_error(
    content: bytes,
    key: bytes,
    subkey: bytes | int | None,
    message: str,
) -> InvalidValueParseException:
    key_text = "[" + json.dumps(key) + "]"
    subkey_text = "[" + json.dumps(subkey) + "]" if subkey is not None else ""

    message = f"Key {key_text}{subkey_text} {message} in message {json.dumps(content)}."
    raise InvalidValueParseException(message)


class HostMessageParser(Parser):
    def peek_not_space(self, ahead: int = 0) -> bytes | None:
        character = self.peek(ahead)
        if not character or character.isspace():
            return None

        return character

    def eat_command(self) -> bytes | None:
        command = self.eat_while(lambda current: current.isalpha())
        if not command:
            return None
        return command

    def eat_address(self) -> int | None:
        if not self.eat(b":"):
            return None

        address = self.eat_while(lambda current: current.isalnum())
        if not self.eat(b",") and not self.eat(b";"):
            return None
        if not address:
            return None

        try:
            return int(address)
        except Exception:
            return None

    def eat_parameter(self) -> tuple[bytes, bytes] | None:
        name = self.eat_while(lambda current: current.isalpha())
        if not name:
            return None

        next = self.peek_not_space()
        if not next:
            return name, b"true"

        value = self.eat_while(lambda current: current not in b",[]")
        self.eat(b",")

        return name, value


DataT = TypeVar("DataT", bound=DataObject)


class Vector(ImmutableDataObject):
    x: float
    y: float


class Ratio(ImmutableDataObject):
    numerator: float
    denominator: float


class HostMessageInfo(ImmutableDataObject):
    direction: MessageDirection
    timestamp: datetime
    content: bytes

    command: bytes
    address: int | None = None
    data: dict[bytes, list[bytes]] = {}

    @classmethod
    def parse(cls, message: Message) -> "HostMessageInfo":
        parser = HostMessageParser(message.content)

        send = parser.eat(b"<")
        receive = parser.eat(b">")

        if not send and not receive:
            raise ParseException("Expected < or > as first character of message.")

        command = parser.eat_command()
        if not command:
            raise ParseException("No command found in message.")

        address = parser.eat_address()

        data: dict[bytes, list[bytes]] = {}
        while result := parser.eat_parameter():
            name, value = result
            if name in data:
                data[name].append(value)
            else:
                data[name] = [value]

        return HostMessageInfo(
            direction=message.direction,
            timestamp=message.timestamp,
            content=message.content,
            command=command,
            address=address,
            data=data,
        )

    def _get(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> bytes:
        def error() -> DoesNotExistParseException:
            return _host_does_not_exist_error(self.content, key, subkey, "was not found")

        values = self.data.get(key)
        if not values:
            raise error()

        try:
            value = values[index]
        except IndexError:
            raise error()

        if subkey is None:
            parser = Parser(value)
            return parser.eat_while(lambda character: character != b";")

        if isinstance(subkey, int):
            split = value.split(b";")
            try:
                return split[subkey]
            except Exception:
                raise error()

        if isinstance(subkey, bytes):
            parser = Parser(value)
            while (parser.peek() or "").strip():
                if parser.eat(subkey):
                    return parser.eat_while(lambda character: character != b";")

                parser.next()

            raise error()

        raise error()

    def get_text(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> bytes:
        return self._get(key, subkey, index)

    def get_text_or_none(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> bytes | None:
        try:
            return self.get_text(key, subkey, index)
        except ParseException:
            return None

    def get_bool(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> bool:
        try:
            self._get(key, subkey, index)
            return True
        except ParseException:
            return False

    def get_int(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> int:
        value = self._get(key, subkey, index)
        try:
            return int(value)
        except ValueError:
            raise _host_invalid_value_error(self.content, key, subkey, "could not be parsed as int")

    def get_int_or_none(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> int | None:
        try:
            return self.get_int(key, subkey, index)
        except DoesNotExistParseException:
            return None

    def get_float(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> float:
        value = self._get(key, subkey, index)
        try:
            return float(value)
        except ValueError:
            raise _host_invalid_value_error(
                self.content, key, subkey, "could not be parsed as float"
            )

    def get_float_or_none(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> float | None:
        try:
            return self.get_float(key, subkey, index)
        except DoesNotExistParseException:
            return None

    def get_vector(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> Vector:
        value = self._get(key, subkey, index)
        parser = Parser(value)
        xy: list[float] = []

        for _ in range(2):
            if parser.eat(b"-"):
                sign = -1
            elif parser.eat(b"+"):
                sign = 1
            else:
                sign = 1

            try:
                number = float(
                    parser.eat_while(
                        lambda character: str(character).isnumeric() or character == b"."
                    )
                )
            except ValueError:
                raise _host_invalid_value_error(
                    self.content,
                    key,
                    subkey,
                    "could not be parsed as vector",
                )

            xy.append(sign * number)

        x, y = xy
        return Vector(x=x, y=y)

    def get_ratio(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> Ratio:
        value = self._get(key, subkey, index)
        parser = Parser(value)
        numerator: float
        denominator: float

        try:
            numerator = float(
                parser.eat_while(lambda character: str(character).isnumeric() or character == b".")
            )
            parser.eat(b"/")
            denominator = float(
                parser.eat_while(lambda character: str(character).isnumeric() or character == b".")
            )
        except ValueError:
            raise _host_invalid_value_error(
                self.content,
                key,
                subkey,
                "could not be parsed as ratio",
            )

        return Ratio(numerator=numerator, denominator=denominator)

    def get_vector_or_none(
        self,
        key: bytes,
        subkey: bytes | int | None = None,
        index: int = 0,
    ) -> Vector | None:
        try:
            return self.get_vector(key, subkey, index)
        except DoesNotExistParseException:
            return None


class HostMessageData(ImmutableDataObject):
    source: HostMessageInfo

    @classmethod
    def parse(cls: type[Self], message: Message) -> Self:
        raise NotImplementedError()


class HostSENSResponse(HostMessageData):
    pitch: float  # Incline pitch of the unit in degrees.
    roll: float  # Incline roll of the unit in degrees.
    incline_age: int | None = None
    incline_error: int | None = None
    temperature: float  # Ambient temperature reading in degrees celcius.
    temperature_age: int | None = None
    temperature_error: int | None = None
    pressure: float  # Pressure reading in kPa.
    pressure_age: int | None = None
    pressure_error: int | None = None
    secondary_pressure: float | None = None  # Pressure reading in kPa.
    secondary_pressure_age: int | None = None
    secondary_pressure_error: int | None = None
    sound_velocity: float  # Sound velocity reading in degrees celcius.
    sound_velocity_age: int | None = None
    sound_velocity_error: int | None = None

    @classmethod
    def parse(cls, message: Message) -> "HostSENSResponse":
        source = HostMessageInfo.parse(message)
        return HostSENSResponse(
            source=source,
            pitch=source.get_vector(b"INC").x,
            roll=source.get_vector(b"INC").y,
            incline_age=source.get_int_or_none(b"INC", b"AG"),
            incline_error=source.get_int_or_none(b"INC", b"ER"),
            temperature=source.get_float(b"T"),
            temperature_age=source.get_int_or_none(b"T", b"AG"),
            temperature_error=source.get_int_or_none(b"T", b"ER"),
            pressure=source.get_float(b"PR"),
            pressure_age=source.get_int_or_none(b"PR", b"AG"),
            pressure_error=source.get_int_or_none(b"PR", b"ER"),
            secondary_pressure=source.get_float_or_none(b"PR", None, 1),
            secondary_pressure_age=source.get_int_or_none(b"PR", b"AG", 1),
            secondary_pressure_error=source.get_int_or_none(b"PR", b"ER", 1),
            # According to the documentation, we need to add 1000 here to get the real sound
            # velocity value. However, based on testing with the bench system, that appears to be
            # incorrect. It doesn't need to be modified.
            sound_velocity=source.get_float(b"SV"),
            sound_velocity_age=source.get_int_or_none(b"SV", b"AG"),
            sound_velocity_error=source.get_int_or_none(b"SV", b"ER"),
        )

    @property
    def error_count(self) -> int:
        count = 0

        for value in [
            self.incline_error,
            self.temperature_error,
            self.pressure_error,
            self.secondary_pressure_error,
            self.sound_velocity_error,
        ]:
            if value:
                count += 1

        return count


class HostSIResponse(HostMessageData):
    range_delays: dict[int, float]

    @classmethod
    def parse(cls, message: Message) -> "HostSIResponse":
        source = HostMessageInfo.parse(message)
        range_delays: dict[int, float] = {}

        for i in range(len(source.content)):
            address = source.get_int_or_none(b"IR", None, i)
            if address is None:
                break

            value = source.get_float_or_none(b"IR", b"R", i)
            if value is None:
                break

            range_delays[address] = value

        if not range_delays:
            raise ParseException("No range delays found.")

        return HostSIResponse(
            source=source,
            range_delays=range_delays,
        )


class HostCSResponse(HostMessageData):
    turn_around_time: float

    @classmethod
    def parse(cls, message: Message) -> "HostCSResponse":
        source = HostMessageInfo.parse(message)

        return HostCSResponse(source=source, turn_around_time=source.get_float(b"TAT"))


class HostVSResponse(HostMessageData):
    is_external_power_connected: bool  # True if external power is connected to the unit.
    is_tilted: bool  # True if the unit is tilted greater than 45 degrees from vertical.
    is_battery_low_or_tilted: bool  # True if the unit's battery is low or tilted.
    is_using_casius_calibration: bool  # True if the unit is using the Sonardyne calibration mode.
    voltage: float  # Battery or external power voltage.
    current: float  # Current drain/charge in mA. Negative means draining, positive means charging.
    total_battery_capacity: float  # Total battery capacity in Ahr.
    battery_percentage: float  # Percent of battery capacity remaining.
    battery_temperature: float  # Battery temperature in degrees C.
    is_battery_disconnected: bool  # True if the battery is disconnected.
    is_battery_chargeable: bool  # True if the battery type is chargeable.

    @classmethod
    def parse(cls, message: Message) -> "HostVSResponse":
        source = HostMessageInfo.parse(message)
        capacity = source.get_ratio(b"BT", b"CAP")

        return HostVSResponse(
            source=source,
            is_external_power_connected=source.get_bool(b"EXT"),
            is_tilted=source.get_bool(b"TILT"),
            is_battery_low_or_tilted=source.get_bool(b"OV"),
            is_using_casius_calibration=source.get_bool(b"OV"),
            voltage=source.get_float(b"BT", b"VLT"),
            current=source.get_float(b"BT", b"IDC"),
            total_battery_capacity=capacity.numerator,
            battery_percentage=capacity.denominator,
            battery_temperature=source.get_float(b"BT", b"T"),
            is_battery_disconnected=source.get_bool(b"BT", b"DIS"),
            is_battery_chargeable=source.get_bool(b"CHG"),
        )


def _das_does_not_exist_error(
    content: bytes,
    index: int,
    message: str,
) -> DoesNotExistParseException:
    content_display = json.dumps(content.decode("utf-8"))
    message = f"Value at index [{index}] {message} in message {content_display}."
    raise DoesNotExistParseException(message)


def _das_invalid_value_error(
    content: bytes,
    index: int,
    message: str,
) -> InvalidValueParseException:
    content_display = json.dumps(content.decode("utf-8"))
    message = f"Value at index [{index}] {message} in message {content_display}."
    raise InvalidValueParseException(message)


class DASMessageInfo(ImmutableDataObject):
    direction: MessageDirection
    timestamp: datetime
    content: bytes

    command: bytes | None
    das_id: bytes | None
    values: list[bytes]
    crc: bytes | None

    @classmethod
    def parse(cls, message: Message) -> Self:
        parser = Parser(message.content)

        send = parser.eat(b"@")
        receive = parser.eat(b"%")

        if not send and not receive:
            raise ParseException("Expected '@' or '%' as first character of message.")

        command = parser.eat_while(lambda character: character.isalpha())
        if not command:
            command = None

        if send:
            if not parser.eat(b"$"):
                raise ParseException("Expected '$' to follow command name.")
        elif command is not None and not parser.eat(b","):
            raise ParseException("Expected ',' to follow command name.")

        try:
            das_id = parser.eat_while(lambda character: str(character).isnumeric())
        except Exception:
            raise ParseException("Expected DAS ID.")

        parser.eat(b",")

        values = parser.remaining.split(b",")

        crc: bytes | None = None

        if values:
            last = values[-1]
            if b"*" in last:
                index = last.rindex(b"*")
                values[-1] = last[:index]
                crc = str(last)[index + 1 :].encode()

        return DASMessageInfo(
            direction=message.direction,
            timestamp=message.timestamp,
            content=message.content,
            command=command,
            das_id=das_id,
            values=values,
            crc=crc,
        )

    def _get(self, index: int) -> bytes:
        def error() -> DoesNotExistParseException:
            return _das_does_not_exist_error(self.content, index, "was not found")

        try:
            return self.values[index]
        except IndexError:
            raise error()

    def get_text(self, index: int) -> bytes:
        return self._get(index)

    def get_text_or_none(self, index: int) -> bytes | None:
        try:
            return self._get(index)
        except DoesNotExistParseException:
            return None

    def get_int(self, index: int = 0) -> int:
        value = self._get(index)
        try:
            return int(value)
        except ValueError:
            raise _das_invalid_value_error(self.content, index, "could not be parsed as int")

    def get_int_or_none(self, index: int = 0) -> int | None:
        try:
            return self.get_int(index)
        except DoesNotExistParseException:
            return None

    def get_float(self, index: int = 0) -> float:
        value = self._get(index)
        try:
            return float(value)
        except ValueError:
            raise _das_invalid_value_error(self.content, index, "could not be parsed as float")

    def get_float_or_none(self, index: int = 0) -> float | None:
        try:
            return self.get_float(index)
        except DoesNotExistParseException:
            return None


class DASMessageData(ImmutableDataObject):
    source: DASMessageInfo

    @classmethod
    def parse(cls: type[Self], message: Message) -> Self:
        raise NotImplementedError()


class BaseDASAZAResponse(DASMessageData):
    transfer_sensor_pressure: float
    transfer_sensor_temperature: float
    ambient_sensor_pressure: float
    ambient_sensor_temperature: float
    low_pressure_sensor_pressure: float
    low_pressure_sensor_temperature: float


class DASAZSResponse(BaseDASAZAResponse):
    @classmethod
    def parse(cls, message: Message) -> "DASAZSResponse":
        source = DASMessageInfo.parse(message)
        return DASAZSResponse(
            source=source,
            transfer_sensor_pressure=source.get_float(6),
            transfer_sensor_temperature=source.get_float(7),
            ambient_sensor_pressure=source.get_float(8),
            ambient_sensor_temperature=source.get_float(9),
            low_pressure_sensor_pressure=source.get_float(10),
            low_pressure_sensor_temperature=source.get_float(11),
        )


class DASAZAResponse(BaseDASAZAResponse):
    offset_time: float  # Seconds since the start of the AZA cycle.

    @classmethod
    def parse(cls, message: Message) -> "DASAZAResponse":
        source = DASMessageInfo.parse(message)
        return DASAZAResponse(
            source=source,
            offset_time=source.get_float(4) * 10,
            transfer_sensor_pressure=source.get_float(7),
            transfer_sensor_temperature=source.get_float(8),
            ambient_sensor_pressure=source.get_float(9),
            ambient_sensor_temperature=source.get_float(10),
            low_pressure_sensor_pressure=source.get_float(11),
            low_pressure_sensor_temperature=source.get_float(12),
        )


class DASLoggedTIMMessage(DASMessageData):
    @classmethod
    def parse(cls, message: Message) -> Self:
        source = DASMessageInfo.parse(message)
        if source.command or b"TIM," not in source.content:
            raise ParseException("Invalid logged TIM message.")

        return cls(
            source=source,
        )


class DASLoggedTMPMessage(DASMessageData):
    temperature: float

    @classmethod
    def parse(cls, message: Message) -> Self:
        source = DASMessageInfo.parse(message)
        if source.command or b"TMP," not in source.content:
            raise ParseException("Invalid logged TMP message.")

        return cls(
            source=source,
            temperature=source.get_float(5),
        )


class DASLoggedINCMessage(DASMessageData):
    pitch: float
    roll: float

    @classmethod
    def parse(cls, message: Message) -> Self:
        source = DASMessageInfo.parse(message)
        if source.command or b"INC," not in source.content:
            raise ParseException("Invalid logged INC message.")

        return cls(
            source=source,
            pitch=source.get_float(5),
            roll=source.get_float(6),
        )


class DASLoggedDQZMessage(DASMessageData):
    pressure: float
    temperature: float

    @classmethod
    def parse(cls, message: Message) -> Self:
        source = DASMessageInfo.parse(message)
        if source.command or b"DQZ," not in source.content:
            raise ParseException("Invalid logged DQZ message.")

        return cls(
            source=source,
            pressure=source.get_float(5),
            temperature=source.get_float(6),
        )


class DASLoggedPRSMessage(DASMessageData):
    pressure: float
    temperature: float

    @classmethod
    def parse(cls, message: Message) -> Self:
        source = DASMessageInfo.parse(message)
        if source.command or b"PRS," not in source.content:
            raise ParseException("Invalid logged PRS message.")

        return cls(
            source=source,
            pressure=source.get_float(5),
            temperature=source.get_float(6),
        )


DASLoggedMessage = (
    DASLoggedTIMMessage
    | DASLoggedTMPMessage
    | DASLoggedINCMessage
    | DASLoggedDQZMessage
    | DASLoggedPRSMessage
)


def parse_logged_das_message(message: Message) -> DASLoggedMessage:
    classes: list[type[DASLoggedMessage]] = [
        DASLoggedTIMMessage,
        DASLoggedTMPMessage,
        DASLoggedINCMessage,
        DASLoggedDQZMessage,
        DASLoggedPRSMessage,
    ]

    for cls in classes:
        try:
            return cls.parse(message)
        except ParseException:
            continue

    raise ParseException(f"Failed to parse logged DAS message: {message.content}")
