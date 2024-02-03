from typing import Annotated

from ceres.alert import Alert
from ceres.data import jsonify
from ceres.filter import AlertFilter
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import ValidateEmptyAsNone, use_temporary_engine, write

router = CLIRouter(
    name="alert",
    help="Manage alerts.",
)


class CLIAlertFilter(AlertFilter, ValidateEmptyAsNone):
    pass


@router.command()
async def select(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Retrieve alerts.
    """
    engine = await use_temporary_engine(context)
    user = await engine.get_alerts(filter)
    write(jsonify(user, indent=2))


@router.command()
async def create(
    *,
    data: Annotated[Alert, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Create an alert.
    """
    engine = await use_temporary_engine(context)
    alert = await engine.create_alert(data)
    write(jsonify(alert, indent=2))
