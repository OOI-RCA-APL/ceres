"""What the migration display draws, which is the part a unit test can still pin.

The drawing itself belongs to rich. What is worth holding still is the decision about
what the display claims because a check mark over a migration that failed, or a count
that runs ahead of what landed, says the opposite of what happened.
"""

from typing import TYPE_CHECKING, cast

from ceres.__internal__.cli.subcommands.database import MigrationProgress
from ceres.database.migrations import Migration

if TYPE_CHECKING:
    from rich.progress import Progress


def _migration(id: int, name: str) -> Migration:
    """A migration with no scripts, which is all the display reads from one."""
    return Migration(id=id, name=name, scripts={})


class Recorder:
    """Stands in for a `rich.progress.Progress`, recording what it was asked to draw."""

    def __init__(self) -> None:
        self.tasks: list[dict[str, object]] = []
        self.updates: list[tuple[int, dict[str, object]]] = []

    def add_task(self, description: str, **fields: object) -> int:
        self.tasks.append({"description": description, **fields})
        return len(self.tasks) - 1

    def update(self, task: int, **fields: object) -> None:
        self.updates.append((task, fields))


def _progress() -> tuple[Recorder, MigrationProgress]:
    recorder = Recorder()
    return recorder, MigrationProgress(cast("Progress", recorder))


def test_the_whole_batch_shares_one_line():
    """A line per migration would spend the display on a list the reader just confirmed.

    A migration runs as a single script so all that changes between them is which is
    running, which one line can say as well as many.
    """
    recorder, progress = _progress()
    pending = [
        _migration(1, "init"),
        _migration(2, "remove-user-roles"),
        _migration(3, "component-forest"),
    ]

    for index, migration in enumerate(pending):
        progress.starting(migration, index, len(pending))
        progress.finished(migration)

    assert len(recorder.tasks) == 1
    assert recorder.tasks[0]["total"] == len(pending)


def test_the_task_counts_the_migrations_that_landed():
    """Reaching the total turns the spinner into a check so it has to be exact."""
    recorder, progress = _progress()
    pending = [_migration(1, "init"), _migration(2, "remove-user-roles")]

    for index, migration in enumerate(pending):
        progress.starting(migration, index, len(pending))
        progress.finished(migration)

    completed = [fields["completed"] for _, fields in recorder.updates if "completed" in fields]
    assert completed == [1, 2]


def test_a_migration_that_never_finishes_leaves_the_count_where_it_was():
    """Counting on starting would show a check over a migration that in fact failed."""
    recorder, progress = _progress()

    progress.starting(_migration(1, "init"), 0, 2)
    progress.finished(_migration(1, "init"))
    # The second one starts and then fails so nothing reports it finished.
    progress.starting(_migration(2, "remove-user-roles"), 1, 2)

    completed = [fields["completed"] for _, fields in recorder.updates if "completed" in fields]
    assert completed == [1]


def test_the_running_migration_is_named_beside_the_count():
    """One line means the label is the only thing saying which migration is running."""
    recorder, progress = _progress()

    progress.starting(_migration(1, "init"), 0, 2)
    progress.finished(_migration(1, "init"))
    progress.starting(_migration(2, "remove-user-roles"), 1, 2)

    assert recorder.tasks[0]["description"] == "0001 init"
    assert recorder.tasks[0]["note"] == "(1/2)"

    described = [fields for _, fields in recorder.updates if "description" in fields]
    assert described[-1]["description"] == "0002 remove-user-roles"
    assert described[-1]["note"] == "(2/2)"
