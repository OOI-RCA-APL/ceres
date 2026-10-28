"""Exports of records a load wrote straight to the database, past the engine's live writes."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio

from ceres.address import Address
from ceres.data import DataObject, DateTime, validate
from ceres.entity import EntityType
from ceres.error import AlreadyExistsError
from ceres.exporter import TICK

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from ceres.component import ComponentSystem
    from ceres.engine import Engine

PENDING_EXPORTS_FILE = "pending-exports.jsonl"
"""File in the project's `.ceres` directory where a load leaves its exports while no engine runs."""


class PendingExport(DataObject):
    """Records of one kind at one address that a load wrote, to merge into the exporters' files."""

    kind: EntityType
    """Kind of the records."""

    address: Address
    """Address the records belong to."""

    first: DateTime
    """Timestamp of the oldest record."""

    last: DateTime
    """Timestamp of the newest record."""


@dataclass
class _PendingRun:
    """One exporter's merge over every entry it takes."""

    system: ComponentSystem
    exporter: str
    first: datetime
    last: datetime
    addresses: dict[Address, None]


async def export_pending(engine: Engine, entries: Sequence[PendingExport]) -> None:
    """Merge the entries' records into the files of every exporter that exports them.

    An exporter of an entry's kind on a running component whose address contains the entry's
    takes it. Each exporter runs one merge, from the oldest record of the entries it takes to
    the newest, so a load across many addresses rewrites each file once. A format that cannot
    merge keeps its files, and an entry no exporter takes is dropped. Each run logs one line,
    and so does each dropped entry.
    """
    runs: dict[tuple[Address, str], _PendingRun] = {}
    for entry in entries:
        taken = False
        for component in engine.get_components(running=True):
            system = component.system
            if not system.address.contains(entry.address):
                continue

            for exporter in system.exporters.get_all():
                if exporter.exports != entry.kind or not exporter.format_class.keyed:
                    continue

                taken = True
                run = runs.get((system.address, exporter.name))
                if run is None:
                    runs[system.address, exporter.name] = _PendingRun(
                        system, exporter.name, entry.first, entry.last, {entry.address: None}
                    )
                else:
                    run.first = min(run.first, entry.first)
                    run.last = max(run.last, entry.last)
                    run.addresses[entry.address] = None

        if not taken:
            engine.log.info(
                f"No exporter takes the loaded {entry.kind} records of '{entry.address}' "
                f"{_span(entry.first, entry.last)}"
            )

    for run in runs.values():
        addresses = ", ".join(f"'{address}'" for address in run.addresses)
        try:
            await run.system.exporters.run(run.exporter, run.first, run.last + TICK)
        except AlreadyExistsError:
            engine.log.warning(
                f"Exporter '{run.exporter}' of '{run.system.address}' already has a run waiting, "
                f"so it skips the loaded records of {addresses}"
            )
            continue

        engine.log.info(
            f"Exported the loaded records of {addresses} {_span(run.first, run.last)} through "
            f"'{run.system.address}' '{run.exporter}'"
        )


def _span(first: datetime, last: datetime) -> str:
    return f"from {first.isoformat()} to {last.isoformat()}"


async def drain_pending_exports(engine: Engine, directory: Path) -> None:
    """Export what loads left in `directory`'s pending exports file while no engine ran.

    The file is renamed before it is read, so a load appending meanwhile starts a new one, and
    removed once every entry has run. A claimed file an earlier engine stopped on runs whole
    first, which repeats nothing a merge has not already written. A line that does not parse is
    logged and skipped.
    """
    pending = anyio.Path(directory / PENDING_EXPORTS_FILE)
    claimed = pending.with_suffix(".processing")
    for source in (claimed, pending):
        if not await source.exists():
            continue

        if source == pending:
            await pending.rename(claimed)

        entries: list[PendingExport] = []
        for number, line in enumerate((await claimed.read_text()).splitlines(), start=1):
            if not line.strip():
                continue

            try:
                entries.append(validate(PendingExport, json.loads(line)))
            except ValueError as error:
                engine.log.warning(f"Skipping line {number} of '{claimed}'. {error}")

        await export_pending(engine, entries)
        await claimed.unlink()
