"""The CLI's bulk record load.

A load reads a whole file inside one transaction, so the conflict mode decides what a
colliding primary key does, and the count it reports is the number of rows read rather
than the number of rows the database ended up writing.
"""

from typing import TYPE_CHECKING

import pytest

from ceres import Engine
from ceres.__internal__.cli.shared import (
    CLICommandFailed,
    CLIDataConflict,
    create_entity_load_command,
)
from ceres.config import Config
from ceres.data import to_json, validate
from ceres.entity import EntityType
from ceres.logs import LogEntry

if TYPE_CHECKING:
    from pathlib import Path

FIRST = (
    '{"id": "0198c0de-0000-7000-8000-000000000001", "address": "@a", '
    '"timestamp": "2026-07-29T00:00:00Z", "level": "info", "content": "before"}'
)
SECOND = (
    '{"id": "0198c0de-0000-7000-8000-000000000001", "address": "@zzz", '
    '"timestamp": "2026-07-30T00:00:00Z", "level": "error", "content": "after"}'
)


async def _build_project(tmp_path: Path) -> Engine:
    """Write a project config on a file-backed database and migrate it."""
    (tmp_path / "ceres.yaml").write_text(
        "components: []\ndatabase:\n  type: sqlite\n  path: records.sqlite\n"
    )
    engine = Engine()
    await engine.load(
        validate(
            Config,
            {
                "components": [],
                "database": {"type": "sqlite", "path": str(tmp_path / "records.sqlite")},
            },
        ),
        checks=(),
    )
    await engine.database.migrate()
    return engine


async def _load(tmp_path: Path, lines: str, conflict: CLIDataConflict) -> int:
    """Run one load of the given JSONL text against the project in `tmp_path`."""
    path = tmp_path / "entries.jsonl"
    path.write_text(lines)
    Command = create_entity_load_command(LogEntry)
    command = Command(path=path, config=tmp_path / "ceres.yaml", on_conflict=conflict)
    return await command._load(path, EntityType.from_class(LogEntry), None, conflict)


async def _contents(engine: Engine) -> list[dict[str, object]]:
    """Every stored entry as its wire object."""
    import json

    return [json.loads(to_json(entry)) for entry in await engine.logs.where()]


async def test_a_load_reports_the_number_of_rows_read(tmp_path: Path) -> None:
    """The count is the file's row count, not the number of rows the database wrote."""
    engine = await _build_project(tmp_path)

    try:
        assert await _load(tmp_path, f"{FIRST}\n", CLIDataConflict.ERROR) == 1
        # Every row collides, so nothing is written, and the count is still the file's.
        assert await _load(tmp_path, f"{FIRST}\n", CLIDataConflict.IGNORE) == 1
    finally:
        await engine.database.dispose()


async def test_an_ignored_conflict_keeps_the_stored_row(tmp_path: Path) -> None:
    """`ignore` skips a colliding row and leaves the stored values untouched."""
    engine = await _build_project(tmp_path)

    try:
        await _load(tmp_path, f"{FIRST}\n", CLIDataConflict.ERROR)
        await _load(tmp_path, f"{SECOND}\n", CLIDataConflict.IGNORE)

        assert [entry["content"] for entry in await _contents(engine)] == ["before"]
    finally:
        await engine.database.dispose()


async def test_an_updated_conflict_takes_every_incoming_value(tmp_path: Path) -> None:
    """`update` replaces every non-key column with the incoming row's value."""
    engine = await _build_project(tmp_path)

    try:
        await _load(tmp_path, f"{FIRST}\n", CLIDataConflict.ERROR)
        await _load(tmp_path, f"{SECOND}\n", CLIDataConflict.UPDATE)

        stored = await _contents(engine)
        assert [entry["content"] for entry in stored] == ["after"]
        assert [entry["address"] for entry in stored] == ["@zzz"]
        assert [entry["level"] for entry in stored] == ["error"]
    finally:
        await engine.database.dispose()


async def test_a_conflict_rolls_the_whole_load_back(tmp_path: Path) -> None:
    """`error` aborts the transaction, so rows that preceded the collision are gone."""
    engine = await _build_project(tmp_path)
    fresh = (
        '{"id": "0198c0de-0000-7000-8000-000000000009", "address": "@b", '
        '"timestamp": "2026-07-29T00:00:00Z", "level": "info", "content": "fresh"}'
    )

    try:
        await _load(tmp_path, f"{FIRST}\n", CLIDataConflict.ERROR)
        with pytest.raises(Exception):
            await _load(tmp_path, f"{fresh}\n{SECOND}\n", CLIDataConflict.ERROR)

        assert [entry["content"] for entry in await _contents(engine)] == ["before"]
    finally:
        await engine.database.dispose()


async def test_an_invalid_row_fails_the_load_without_writing(tmp_path: Path) -> None:
    """A row that will not validate leaves the table untouched and reports Pydantic's error."""
    engine = await _build_project(tmp_path)
    invalid = '{"id": "not a uuid", "address": "@b", "level": "info", "content": "x"}'

    try:
        with pytest.raises(CLICommandFailed):
            await _load(tmp_path, f"{FIRST}\n{invalid}\n", CLIDataConflict.ERROR)

        assert await _contents(engine) == []
    finally:
        await engine.database.dispose()
