from dataclasses import field

from ceres.alert import Alert, AlertLevel
from ceres.component import Component
from ceres.events import Event
from ceres.internal.database import Database
from ceres.listener import on


async def test_event_listeners(database: Database) -> None:
    class EmitterEvent(Event):
        kind: str = "emitter-event"
        value: int

    class SelfEvent(Event):
        kind: str = "self-event"
        value: int

    class Emitter(Component):
        pass

    class Receiver(Component):
        received_emitter_events: list[EmitterEvent] = field(default_factory=list)
        received_self_events: list[SelfEvent] = field(default_factory=list)

        class References(Component.References):
            emitter: Emitter

        references: References

        @on(EmitterEvent, "emitter")
        def _on_other_event(self, event: EmitterEvent) -> None:
            self.received_emitter_events.append(event)

        @on(SelfEvent)
        def _on_self_event(self, event: SelfEvent) -> None:
            self.received_self_events.append(event)

    emitter = Emitter(
        context=Emitter.Context(database=database),
    )
    receiver = Receiver(
        context=Receiver.Context(database=database),
        references=Receiver.References(emitter=emitter),
    )

    receiver.start()
    emitter.start()

    emitter.emit_event(EmitterEvent(value=0))
    receiver.emit_event(SelfEvent(value=0))
    emitter.emit_event(EmitterEvent(value=1))
    receiver.emit_event(SelfEvent(value=1))

    await receiver.settle()
    assert [(type(event), event.value) for event in receiver.received_emitter_events] == [
        (EmitterEvent, 0),
        (EmitterEvent, 1),
    ]
    assert [(type(event), event.value) for event in receiver.received_self_events] == [
        (SelfEvent, 0),
        (SelfEvent, 1),
    ]

    await emitter.stop()
    await receiver.stop()


async def test_component_alerts() -> None:
    class Test(Component):
        pass

    component = Test()
    component.start()
    component.emit_alert(
        Alert(
            level=AlertLevel.ERROR,
            code="test-alert-1",
        )
    )
    component.emit_alert(
        Alert(
            level=AlertLevel.ERROR,
            code="test-alert-2",
        )
    )

    await component.settle()
    assert len(await component.database.entities.get_alerts()) == 2
    await component.stop()
