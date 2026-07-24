from ceres.__internal__.workspace_redaction import (
    iter_widget_targets,
    redact_workspace_data,
)
from ceres.address import Address


def test_iter_widget_targets_extracts_absolute_button_address() -> None:
    widget = {"id": "w1", "type": "button", "address": "@rig.pump", "width": 60}
    assert list(iter_widget_targets(widget, None)) == [Address("@rig.pump")]


def test_iter_widget_targets_resolves_relative_against_scope() -> None:
    widget = {"id": "w1", "type": "button", "address": "pump", "width": 60}
    assert list(iter_widget_targets(widget, Address("@rig"))) == [Address("@rig.pump")]


def test_iter_widget_targets_empty_relative_is_scope_itself() -> None:
    widget = {"id": "w1", "type": "value", "particleAddress": "", "width": 60}
    assert list(iter_widget_targets(widget, Address("@rig"))) == [Address("@rig")]


def test_iter_widget_targets_reads_chart_particles() -> None:
    widget = {
        "id": "w1",
        "type": "chart",
        "width": 60,
        "particles": [
            {"address": "@rig.pump:all"},
            {"address": "sensor"},
        ],
    }
    assert list(iter_widget_targets(widget, Address("@rig"))) == [
        Address("@rig.pump"),
        Address("@rig.sensor"),
    ]


def test_iter_widget_targets_reads_filter_address() -> None:
    widget = {
        "id": "w1",
        "type": "particles",
        "width": 60,
        "filter": {"address": "@rig.pump:descendants"},
    }
    assert list(iter_widget_targets(widget, None)) == [Address("@rig.pump")]


def test_redact_replaces_denied_widget_with_stub() -> None:
    data = {
        "layout": [
            {
                "widgets": [
                    {
                        "id": "w1",
                        "type": "button",
                        "name": "Stop",
                        "address": "@secret.pump",
                        "action": "stop",
                        "width": 60,
                    },
                    {
                        "id": "w2",
                        "type": "button",
                        "name": "Go",
                        "address": "@open.pump",
                        "action": "start",
                        "width": 60,
                    },
                ]
            }
        ]
    }

    redacted = redact_workspace_data(
        data,
        scope=None,
        can_view=lambda address: not str(address).startswith("@secret"),
    )

    stub, kept = redacted["layout"][0]["widgets"]
    assert stub == {"id": "w1", "type": "button", "name": "", "width": 60, "restricted": True}
    assert kept["address"] == "@open.pump"
    # The input is not mutated.
    assert data["layout"][0]["widgets"][0]["action"] == "stop"


def test_redact_keeps_widgets_without_targets() -> None:
    data = {"layout": [{"widgets": [{"id": "w1", "type": "particles", "width": 60}]}]}
    redacted = redact_workspace_data(data, scope=None, can_view=lambda address: False)
    assert redacted["layout"][0]["widgets"][0]["id"] == "w1"
    assert "restricted" not in redacted["layout"][0]["widgets"][0]
