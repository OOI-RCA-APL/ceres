"""Per-viewer redaction of workspace data.

Workspace payloads embed widget configurations that reference components by address. A viewer
without view access on a referenced component must not receive that widget's configuration,
because addresses, labels, and series definitions all leak information about components that
are supposed to be invisible. `redact_workspace_data` walks a workspace `data` payload and
replaces any widget whose target the viewer cannot view with a restricted stub.

Only named component addresses are treated as targets. Wildcard selectors such as `@:all`
name no component, so their widgets carry nothing to hide and pass through unredacted, the
data they display is still gated per component by the record APIs at fetch time.
"""

from collections.abc import Callable, Iterator
from copy import deepcopy
from typing import Any

from ceres.address import Address, AddressSelector

__all__ = [
    "iter_widget_targets",
    "redact_workspace_data",
]

_ADDRESS_KEYS = (
    "address",
    "commandAddress",
    "interfaceAddress",
    "particleAddress",
    "procedureAddress",
)
"""Widget configuration keys that hold a component address or selector."""


def _iter_raw_values(widget: dict[str, Any]) -> Iterator[Any]:
    for key in _ADDRESS_KEYS:
        yield widget.get(key)

    filter_value = widget.get("filter")
    if isinstance(filter_value, dict):
        yield filter_value.get("address")

    particles = widget.get("particles")
    if isinstance(particles, list):
        for particle in particles:
            if isinstance(particle, dict):
                yield particle.get("address")


def _selector_bases(value: str, scope: Address | None) -> Iterator[Address]:
    """Yield the base component address of each segment of a selector string."""
    try:
        selector = AddressSelector(value).as_absolute(scope)
    except ValueError:
        return

    for segment in selector.segments:
        base = segment.text.split(":", 1)[0]
        if not base.startswith("@"):
            continue

        try:
            yield Address(base)
        except ValueError:
            continue


def iter_widget_targets(widget: dict[str, Any], scope: Address | None) -> Iterator[Address]:
    """Yield every component address a widget's configuration references.

    Relative values resolve against `scope`. An empty string refers to the scope itself.
    Values that fail to parse are skipped, redaction is a safety net and must not reject
    payloads that widget models themselves tolerate.
    """
    for value in _iter_raw_values(widget):
        if not isinstance(value, str):
            continue

        if value == "":
            if scope is not None:
                yield scope

            continue

        yield from _selector_bases(value, scope)


def redact_workspace_data(
    data: dict[str, Any],
    *,
    scope: Address | None,
    can_view: Callable[[Address], bool],
) -> dict[str, Any]:
    """Return a copy of `data` with denied widgets replaced by restricted stubs.

    A widget is denied when any of its targets fails `can_view`. The stub keeps only the
    widget's identity and layout fields plus `restricted: true`, everything else is stripped.
    """
    result = deepcopy(data)
    layout = result.get("layout")
    if not isinstance(layout, list):
        return result

    for row in layout:
        if not isinstance(row, dict):
            continue

        widgets = row.get("widgets")
        if not isinstance(widgets, list):
            continue

        for index, widget in enumerate(widgets):
            if not isinstance(widget, dict):
                continue

            targets = list(iter_widget_targets(widget, scope))
            if targets and not all(can_view(target) for target in targets):
                widgets[index] = {
                    "id": widget.get("id"),
                    "type": widget.get("type"),
                    "name": "",
                    "width": widget.get("width"),
                    "restricted": True,
                }

    return result
