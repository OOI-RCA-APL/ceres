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
from ceres.exporter import TICK, ExportConflict, ExportConflictError, ExportRangeMode

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from ceres.component import ComponentSystem
    from ceres.engine import Engine

PENDING_EXPORTS_FILE = "pending-exports.jsonl"
"""File in the project's `.ceres` directory where a load leaves its exports while no engine runs."""


class PendingExport(DataObject):
    """Records of one kind at one address that a load wrote, to export to the exporters' files."""

    kind: EntityType
    """Kind of the records."""

    address: Address
    """Address the records belong to."""

    first: DateTime
    """Timestamp of the oldest record."""

    last: DateTime
    """Timestamp of the newest record."""

    on_conflict: ExportConflict = ExportConflict.OVERWRITE
    """What the export runs do with a file that already exists."""

    range_mode: ExportRangeMode = ExportRangeMode.EXPAND
    """How the export runs align the loaded range with the exporters' files."""


@dataclass
class _PendingRun:
    """One exporter's run over every entry it takes with the same modes."""

    system: ComponentSystem
    exporter: str
    first: datetime
    last: datetime
    on_conflict: ExportConflict
    range_mode: ExportRangeMode
    addresses: dict[Address, None]


async def export_pending(engine: Engine, entries: Sequence[PendingExport]) -> None:
    """Run every exporter that exports the entries' records over the times they cover.

    An exporter of an entry's kind on a running component whose address contains the entry's
    takes it. Each exporter runs once per pair of modes, from the oldest record of the entries
    it takes to the newest, so a load across many addresses writes each file once. An entry no
    exporter takes is dropped. Each run logs one line, and so does each dropped entry and each
    run that fails, with the command that retries it.
    """
    runs: dict[tuple[Address, str, ExportConflict, ExportRangeMode], _PendingRun] = {}
    for entry in entries:
        taken = False
        for component in engine.get_components(running=True):
            system = component.system
            if not system.address.contains(entry.address):
                continue

            for exporter in system.exporters.get_all():
                if exporter.exports != entry.kind:
                    continue

                taken = True
                key = (system.address, exporter.name, entry.on_conflict, entry.range_mode)
                run = runs.get(key)
                if run is None:
                    runs[key] = _PendingRun(
                        system,
                        exporter.name,
                        entry.first,
                        entry.last,
                        entry.on_conflict,
                        entry.range_mode,
                        {entry.address: None},
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
        retry = (
            f"`ceres export {run.system.address} {run.exporter} --after "
            f"{run.first.isoformat()} --before {(run.last + TICK).isoformat()}`"
        )
        try:
            finished = await run.system.exporters.run(
                run.exporter,
                run.first,
                run.last + TICK,
                on_conflict=run.on_conflict,
                range_mode=run.range_mode,
            )
        except (AlreadyExistsError, ExportConflictError) as error:
            reason = (
                "already has a run waiting"
                if isinstance(error, AlreadyExistsError)
                else f"refused the run. {error}"
            )
            engine.log.warning(
                f"Exporter '{run.exporter}' of '{run.system.address}' {reason}, so it skips the "
                f"loaded records of {addresses}. Run {retry} to export them."
            )
            continue

        if finished.exception is not None:
            engine.log.warning(
                f"Exporter '{run.exporter}' of '{run.system.address}' failed to export the "
                f"loaded records of {addresses}: {finished.exception}. Run {retry} to retry."
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
    first. A line that does not parse is logged and skipped, and a run that fails logs the
    command that retries it.
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
