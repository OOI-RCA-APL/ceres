"""Cover `declared_particle_classes` against sieves, unions, and `__particles__`."""

import json
from collections.abc import AsyncIterable, AsyncIterator
from enum import StrEnum
from typing import Annotated

from ceres import Component, Message, Particle, ParticleData, Unit, sieve
from ceres.__internal__.app.handlers.components import (
    ParticleTypeInfo,
    _describe_particle_class,
)
from ceres.__internal__.particles import declared_particle_classes


class TemperatureData(ParticleData):
    celsius: float
    """Degrees Celsius."""


class Temperature(Particle[TemperatureData]):
    type = "temperature"
    data: TemperatureData


class HumidityData(ParticleData):
    percent: float


class Humidity(Particle[HumidityData]):
    type = "humidity"
    data: HumidityData


class Undiscriminated(Particle[TemperatureData]):
    __abstract__ = True
    data: TemperatureData


def _build(cls: type[Component]) -> Component:
    """Instantiate `cls` standalone, the way `component.system.sieves` gets populated."""
    return cls()  # type: ignore[reportCallIssue]


def test_sieve_return_annotations_contribute_their_classes():
    class Sensor(Component):
        @sieve
        async def parse(self, messages: AsyncIterable[Message]) -> AsyncIterator[Temperature]:
            async for message in messages:
                yield Temperature(
                    type="temperature", address=message.address, data=TemperatureData(celsius=0.0)
                )

    assert declared_particle_classes(_build(Sensor)) == [Temperature]


def test_union_annotations_contribute_each_member():
    class Sensor(Component):
        @sieve
        async def parse(
            self, messages: AsyncIterable[Message]
        ) -> AsyncIterator[Temperature | Humidity]:
            async for message in messages:
                yield Temperature(
                    type="temperature", address=message.address, data=TemperatureData(celsius=0.0)
                )

    assert declared_particle_classes(_build(Sensor)) == [Humidity, Temperature]


def test_particles_attribute_adds_direct_emitters():
    class Sensor(Component):
        __particles__: tuple[type[Particle], ...] = (Humidity,)

    assert declared_particle_classes(_build(Sensor)) == [Humidity]


def test_undiscriminated_classes_are_skipped():
    class Sensor(Component):
        __particles__: tuple[type[Particle], ...] = (Undiscriminated, Temperature)

    assert declared_particle_classes(_build(Sensor)) == [Temperature]


def test_describe_reads_the_data_model():
    info: ParticleTypeInfo = _describe_particle_class(Temperature)
    assert info.type == "temperature"
    assert [field.name for field in info.fields] == ["celsius"]
    assert info.fields[0].schema["type"] == "number"
    assert info.fields[0].schema["description"] == "Degrees Celsius."


def test_mixed_field_schemas_carry_their_own_types():
    class MixedData(ParticleData):
        label: str
        count: int

    class Mixed(Particle[MixedData]):
        type = "mixed"
        data: MixedData

    info = _describe_particle_class(Mixed)
    by_name = {field.name: field for field in info.fields}
    assert by_name["label"].schema["type"] == "string"
    assert by_name["count"].schema["type"] == "integer"


class Status(StrEnum):
    OK = "ok"
    ERROR = "error"


class StatusData(ParticleData):
    status: Status


class StatusParticle(Particle[StatusData]):
    type = "status"
    data: StatusData


def test_field_schema_refs_are_inlined_against_defs():
    info = _describe_particle_class(StatusParticle)
    schema = info.fields[0].schema
    assert "$ref" not in json.dumps(schema)
    assert schema["enum"] == ["ok", "error"]


def test_unit_marker_reaches_the_field_schema():
    class PressureData(ParticleData):
        pascals: Annotated[float, Unit("Pa")]

    class Pressure(Particle[PressureData]):
        type = "pressure"
        data: PressureData

    info = _describe_particle_class(Pressure)
    assert info.fields[0].schema["unit"] == "Pa"


def test_duplicates_collapse():
    class Sensor(Component):
        __particles__: tuple[type[Particle], ...] = (Temperature,)

        @sieve
        async def parse(self, messages: AsyncIterable[Message]) -> AsyncIterator[Temperature]:
            async for message in messages:
                yield Temperature(
                    type="temperature", address=message.address, data=TemperatureData(celsius=0.0)
                )

    assert declared_particle_classes(_build(Sensor)) == [Temperature]
