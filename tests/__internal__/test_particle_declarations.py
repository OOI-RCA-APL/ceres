"""Cover `declared_particle_classes` against sieves, unions, and `__particles__`."""

from collections.abc import AsyncIterable, AsyncIterator

from ceres import Component, Message, Particle, ParticleData, sieve
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
        __particles__ = (Humidity,)

    assert declared_particle_classes(_build(Sensor)) == [Humidity]


def test_undiscriminated_classes_are_skipped():
    class Sensor(Component):
        __particles__ = (Undiscriminated, Temperature)

    assert declared_particle_classes(_build(Sensor)) == [Temperature]


def test_duplicates_collapse():
    class Sensor(Component):
        __particles__ = (Temperature,)

        @sieve
        async def parse(self, messages: AsyncIterable[Message]) -> AsyncIterator[Temperature]:
            async for message in messages:
                yield Temperature(
                    type="temperature", address=message.address, data=TemperatureData(celsius=0.0)
                )

    assert declared_particle_classes(_build(Sensor)) == [Temperature]
