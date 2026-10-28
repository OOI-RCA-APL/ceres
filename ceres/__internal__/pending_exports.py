"""Exports of records a load wrote straight to the database, past the engine's live writes."""

import json
from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING

import anyio

from ceres.address import Address
from ceres.data import DataObject, DateTime, validate
from ceres.entity import EntityType
from ceres.error import AlreadyExistsError

if TYPE_CHECKING:
    from pathlib import Path

    from ceres.engine import Engine

PENDING_EXPORTS_FILE = "pending-exports.jsonl"
"""File in the project's `.ceres` directory where a load leaves its exports while no engine runs."""

# The smallest step of a stored timestamp, which turns a load's newest record into an exclusive
# end.
_TICK = timedelta(microseconds=1)


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


async def export_pending(engine: Engine, entries: Sequence[PendingExport]) -> None:
    """Merge each entry's records into the files of every exporter that exports them.

    An exporter of the entry's kind on a running component whose address contains the
    entry's runs a merge over the entry's range, one run at a time. A format that cannot merge
    keeps its files, and an entry no exporter takes is dropped. Each entry logs one line.
    """
    for entry in entries:
        ran: list[str] = []
        for component in engine.get_components(running=True):
            system = component.system
            if not system.address.contains(entry.address):
                continue

            exporters = system.exporters
            for exporter in exporters.get_all():
                if exporter.exports != entry.kind or not exporter.format_class.keyed:
                    continue

                try:
                    await exporters.run(exporter.name, entry.first, entry.last + _TICK)
                except AlreadyExistsError:
                    engine.log.warning(
                        f"Exporter '{exporter.name}' of '{system.address}' already has a run "
                        f"waiting, so it skips the loaded {entry.kind} records of "
                        f"'{entry.address}'"
                    )
                    continue

                ran.append(f"'{system.address}' '{exporter.name}'")

        span = f"from {entry.first.isoformat()} to {entry.last.isoformat()}"
        if ran:
            engine.log.info(
                f"Exported the loaded {entry.kind} records of '{entry.address}' {span} through "
                + ", ".join(ran)
            )
        else:
            engine.log.info(
                f"No exporter takes the loaded {entry.kind} records of '{entry.address}' {span}"
            )


async def drain_pending_exports(engine: Engine, directory: Path) -> None:
    """Export what loads left in `directory`'s pending exports file while no engine ran.

    The file is renamed before it is read, so a load appending meanwhile starts a new one, and
    removed once every entry has run. A claimed file an earlier engine stopped on runs first.
    A line that does not parse is logged and skipped.
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
