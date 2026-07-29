from collections.abc import AsyncIterable, AsyncIterator
from typing import override

import pytest

from ceres.address import Address
from ceres.component import sieve as sieve_decorator
from ceres.connection.buffer import (
    Buffer,  # noqa: TC001 - used at runtime by inspect.get_annotations
)
from ceres.message import Message
from ceres.particle import Particle, ParticleData
from ceres.sieve import FunctionSieve, Sieve


class SimpleData(ParticleData):
    value: int


class SimpleParticle(Particle[SimpleData]):
    type = "test/simple"


def _make_message(
    data: bytes,
    connection: str | None = None,
    address: Address = Address("@test"),
) -> Message:
    return Message(
        data=data,
        direction=Message.Direction.RECEIVE,
        address=address,
        connection=connection,
    )


class TestSieveAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Sieve()  # type: ignore[reportAbstractUsage]

    def test_subclass_must_implement_process(self):
        class IncompleteSieve(Sieve):
            pass

        with pytest.raises(TypeError):
            IncompleteSieve()  # type: ignore[reportAbstractUsage]

    def test_concrete_subclass_can_be_instantiated(self):
        class ConcreteSieve(Sieve):
            @override
            async def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[Particle]:
                async for message in messages:
                    yield SimpleParticle(
                        type="test/simple",
                        address=Address("@test"),
                        data=SimpleData(value=int(message.data)),
                    )

        sieve = ConcreteSieve()
        assert isinstance(sieve, Sieve)


class TestFunctionSieveMonoSync:
    async def test_sync_mono_sieve_yields_particles(self):
        def parse(message: Message) -> SimpleParticle | None:
            try:
                value = int(message.data)
            except ValueError:
                return None
            return SimpleParticle(
                type="test/simple",
                address=message.address,
                data=SimpleData(value=value),
            )

        sieve = FunctionSieve(function=parse)

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"10")
            yield _make_message(b"20")
            yield _make_message(b"30")

        results = [particle async for particle in sieve.process(messages())]
        assert len(results) == 3
        assert results[0].data.value == 10
        assert results[1].data.value == 20
        assert results[2].data.value == 30

    async def test_sync_mono_sieve_skips_none(self):
        def parse(message: Message) -> SimpleParticle | None:
            try:
                value = int(message.data)
            except ValueError:
                return None
            return SimpleParticle(
                type="test/simple",
                address=message.address,
                data=SimpleData(value=value),
            )

        sieve = FunctionSieve(function=parse)

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"10")
            yield _make_message(b"not-a-number")
            yield _make_message(b"30")

        results = [particle async for particle in sieve.process(messages())]
        assert len(results) == 2
        assert results[0].data.value == 10
        assert results[1].data.value == 30


class TestFunctionSieveMonoAsync:
    async def test_async_mono_sieve_yields_particles(self):
        async def parse(message: Message) -> SimpleParticle | None:
            value = int(message.data)
            return SimpleParticle(
                type="test/simple",
                address=message.address,
                data=SimpleData(value=value),
            )

        sieve = FunctionSieve(function=parse)

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"42")
            yield _make_message(b"99")

        results = [particle async for particle in sieve.process(messages())]
        assert len(results) == 2
        assert results[0].data.value == 42
        assert results[1].data.value == 99

    async def test_async_mono_sieve_skips_none(self):
        async def parse(message: Message) -> SimpleParticle | None:
            try:
                value = int(message.data)
            except ValueError:
                return None
            return SimpleParticle(
                type="test/simple",
                address=message.address,
                data=SimpleData(value=value),
            )

        sieve = FunctionSieve(function=parse)

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"abc")
            yield _make_message(b"50")

        results = [particle async for particle in sieve.process(messages())]
        assert len(results) == 1
        assert results[0].data.value == 50


class TestFunctionSievePolySieve:
    async def test_poly_sieve_yields_particles(self):
        async def parse(
            messages: AsyncIterable[Message],
        ) -> AsyncIterator[SimpleParticle]:
            async for message in messages:
                value = int(message.data)
                yield SimpleParticle(
                    type="test/simple",
                    address=message.address,
                    data=SimpleData(value=value),
                )

        sieve = FunctionSieve(function=parse)

        async def input_messages() -> AsyncIterator[Message]:
            yield _make_message(b"1")
            yield _make_message(b"2")
            yield _make_message(b"3")

        results = [particle async for particle in sieve.process(input_messages())]
        assert len(results) == 3
        assert [particle.data.value for particle in results] == [1, 2, 3]

    async def test_poly_sieve_can_aggregate_messages(self):
        """A poly sieve can combine multiple messages into one particle."""

        async def parse(
            messages: AsyncIterable[Message],
        ) -> AsyncIterator[SimpleParticle]:
            total = 0
            async for message in messages:
                total += int(message.data)
            yield SimpleParticle(
                type="test/simple",
                address=Address("@test"),
                data=SimpleData(value=total),
            )

        sieve = FunctionSieve(function=parse)

        async def input_messages() -> AsyncIterator[Message]:
            yield _make_message(b"10")
            yield _make_message(b"20")
            yield _make_message(b"30")

        results = [particle async for particle in sieve.process(input_messages())]
        assert len(results) == 1
        assert results[0].data.value == 60


class TestFunctionSieveBufferSieve:
    async def test_buffer_sieve_yields_particles_with_spans(self):
        def parse(buffer: Buffer) -> list[SimpleParticle]:
            import re

            results = []
            for match in re.finditer(rb"(\d+)", buffer.data):
                value = int(match.group(1))
                results.append(
                    SimpleParticle(
                        type="test/simple",
                        address=Address("@test"),
                        data=SimpleData(value=value),
                        span=match.span(),
                    )
                )
            return results

        sieve = FunctionSieve[SimpleParticle](function=parse)  # type: ignore[reportCallIssue]

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"abc 42 def 99")

        results = [particle async for particle in sieve.process(messages())]
        assert len(results) == 2
        assert results[0].data.value == 42
        assert results[1].data.value == 99

    async def test_buffer_sieve_advances_past_consumed_bytes(self):
        """After yielding particles the buffer should drop consumed bytes."""
        call_count = 0

        def parse(buffer: Buffer) -> list[SimpleParticle]:
            nonlocal call_count
            call_count += 1
            import re

            results = []
            for match in re.finditer(rb"(\d+)\n", buffer.data):
                value = int(match.group(1))
                results.append(
                    SimpleParticle(
                        type="test/simple",
                        address=Address("@test"),
                        data=SimpleData(value=value),
                        span=match.span(),
                    )
                )
            return results

        sieve = FunctionSieve[SimpleParticle](function=parse)  # type: ignore[reportCallIssue]

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"10\n")
            yield _make_message(b"20\n")

        results = [particle async for particle in sieve.process(messages())]
        assert len(results) == 2
        assert results[0].data.value == 10
        assert results[1].data.value == 20
        assert call_count == 2

    async def test_buffer_sieve_raises_without_span(self):
        def parse(buffer: Buffer) -> list[SimpleParticle]:
            return [
                SimpleParticle(
                    type="test/simple",
                    address=Address("@test"),
                    data=SimpleData(value=1),
                )
            ]

        sieve = FunctionSieve[SimpleParticle](function=parse)  # type: ignore[reportCallIssue]

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"data")

        with pytest.raises(ValueError, match="span"):
            _ = [particle async for particle in sieve.process(messages())]

    async def test_buffer_sieve_skips_none_results(self):
        def parse(buffer: Buffer) -> list[SimpleParticle | None]:
            return [None, None]

        sieve = FunctionSieve[SimpleParticle](function=parse)  # type: ignore[reportCallIssue]

        async def messages() -> AsyncIterator[Message]:
            yield _make_message(b"data")

        results = [particle async for particle in sieve.process(messages())]
        assert results == []


class TestFunctionSieveSignatureValidation:
    def test_rejects_function_with_no_parameters(self):
        def bad_function() -> None:
            pass

        sieve = FunctionSieve(function=bad_function)  # type: ignore[reportCallIssue]
        with pytest.raises(ValueError, match="exactly one parameter"):
            sieve._get_poly_sieve_function()

    def test_rejects_function_with_two_parameters(self):
        def bad_function(first: Message, second: Message) -> None:
            pass

        sieve = FunctionSieve(function=bad_function)  # type: ignore[reportCallIssue]
        with pytest.raises(ValueError, match="exactly one parameter"):
            sieve._get_poly_sieve_function()

    def test_rejects_unrecognized_parameter_type(self):
        def bad_function(value: int) -> None:
            pass

        sieve = FunctionSieve(function=bad_function)  # type: ignore[reportCallIssue]
        with pytest.raises(TypeError, match="Unrecognized sieve function signature"):
            sieve._get_poly_sieve_function()

    def test_mono_function_gets_name_attribute(self):
        def my_parser(message: Message) -> SimpleParticle | None:
            return None

        sieve = FunctionSieve(function=my_parser)
        poly = sieve._get_poly_sieve_function()
        assert poly.__name__ == "my_parser"

    def test_poly_function_is_returned_as_is(self):
        async def my_poly(
            messages: AsyncIterable[Message],
        ) -> AsyncIterator[SimpleParticle]:
            async for message in messages:
                yield SimpleParticle(
                    type="test/simple",
                    address=Address("@test"),
                    data=SimpleData(value=0),
                )

        sieve = FunctionSieve(function=my_poly)
        poly = sieve._get_poly_sieve_function()
        assert poly is my_poly


class TestFunctionSieveEmptyStream:
    async def test_mono_sieve_with_empty_stream(self):
        def parse(message: Message) -> SimpleParticle | None:
            return SimpleParticle(
                type="test/simple",
                address=Address("@test"),
                data=SimpleData(value=0),
            )

        sieve = FunctionSieve(function=parse)

        async def messages() -> AsyncIterator[Message]:
            return
            yield  # type: ignore[misc]

        results = [particle async for particle in sieve.process(messages())]
        assert results == []

    async def test_buffer_sieve_with_empty_stream(self):
        def parse(buffer: Buffer) -> list[SimpleParticle]:
            return []

        sieve = FunctionSieve[SimpleParticle](function=parse)  # type: ignore[reportCallIssue]

        async def messages() -> AsyncIterator[Message]:
            return
            yield  # type: ignore[misc]

        results = [particle async for particle in sieve.process(messages())]
        assert results == []


class TestSieveConnectionBinding:
    def test_sieve_binding_captures_connection(self):
        from ceres import Bound, Component, Connection, SplitByLine
        from ceres.component import get_sieve_bindings

        class Driver(Component):
            alpha: Bound[Connection] | None = Connection.Field(None, splitter=SplitByLine())
            beta: Bound[Connection] | None = Connection.Field(None, splitter=SplitByLine())

            @sieve_decorator(alpha)
            async def parse_alpha(self, message: Message) -> SimpleParticle | None:
                return None

            @sieve_decorator(beta)
            async def parse_beta(self, message: Message) -> SimpleParticle | None:
                return None

        bindings = get_sieve_bindings(Driver)
        assert "parse-alpha" in bindings
        assert "parse-beta" in bindings
        assert bindings["parse-alpha"].connections is not None
        assert bindings["parse-beta"].connections is not None

    async def test_sieve_filters_messages_by_connection(self):
        from ceres import Bound, Component, Connection, SplitByLine
        from ceres.concurrency import sleep
        from ceres.event import MessageReceivedEvent

        alpha_received: list[Message] = []
        beta_received: list[Message] = []

        class Driver(Component):
            alpha: Bound[Connection] | None = Connection.Field(None, splitter=SplitByLine())
            beta: Bound[Connection] | None = Connection.Field(None, splitter=SplitByLine())

            @sieve_decorator(alpha)
            async def parse_alpha(self, message: Message) -> SimpleParticle | None:
                alpha_received.append(message)
                return None

            @sieve_decorator(beta)
            async def parse_beta(self, message: Message) -> SimpleParticle | None:
                beta_received.append(message)
                return None

        driver = Driver()  # type: ignore[reportCallIssue]
        driver.system.start()
        await sleep(0.1)

        for label in [b"a1", b"a2", b"a3"]:
            driver.system.events.emit(
                MessageReceivedEvent,
                message=_make_message(label, connection="alpha", address=driver.system.address),
            )
        for label in [b"b1", b"b2"]:
            driver.system.events.emit(
                MessageReceivedEvent,
                message=_make_message(label, connection="beta", address=driver.system.address),
            )

        await sleep(0.5)
        await driver.system.stop()

        assert [message.data for message in alpha_received] == [b"a1", b"a2", b"a3"]
        assert [message.data for message in beta_received] == [b"b1", b"b2"]

    async def test_unbound_sieve_receives_all_messages(self):
        from ceres import Bound, Component, Connection, SplitByLine
        from ceres.concurrency import sleep
        from ceres.event import MessageReceivedEvent

        all_received: list[Message] = []

        class Driver(Component):
            alpha: Bound[Connection] | None = Connection.Field(None, splitter=SplitByLine())
            beta: Bound[Connection] | None = Connection.Field(None, splitter=SplitByLine())

            @sieve_decorator
            async def parse_all(self, message: Message) -> SimpleParticle | None:
                all_received.append(message)
                return None

        driver = Driver()  # type: ignore[reportCallIssue]
        driver.system.start()
        await sleep(0.1)

        driver.system.events.emit(
            MessageReceivedEvent,
            message=_make_message(b"a1", connection="alpha", address=driver.system.address),
        )
        driver.system.events.emit(
            MessageReceivedEvent,
            message=_make_message(b"b1", connection="beta", address=driver.system.address),
        )

        await sleep(0.5)
        await driver.system.stop()

        received_data = sorted(message.data for message in all_received)
        assert received_data == [b"a1", b"b1"]
