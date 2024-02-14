import sys
from pathlib import Path
from typing import Annotated

from pydantic import Field, NonNegativeInt

from ceres.config import Config
from ceres.data import jsonify, yamlify
from ceres.engine import Engine
from ceres.internal.cli.plumbing import CLIOption, CLIRouter
from ceres.internal.utilities import StrEnum

router = CLIRouter(
    name="generate",
    help="Generate various project resources.",
)


class OpenAPISchemaFormat(StrEnum):
    yaml = "yaml"
    json = "json"


@router.command()
def openapi(
    *,
    output: Annotated[
        Path | None,
        CLIOption(
            Path | None,
            writable=True,
            file_okay=True,
            dir_okay=False,
        ),
        Field(description="File path to write to. If omitted, standard output is used."),
    ] = None,
    format: Annotated[
        OpenAPISchemaFormat,
        CLIOption(OpenAPISchemaFormat),
        Field(description="Specify the output file format."),
    ] = OpenAPISchemaFormat.yaml,
    indent: Annotated[
        NonNegativeInt,
        CLIOption(int),
        Field(description="Specify indentation size of output."),
    ] = 2,
) -> None:
    """
    Generate up-to-date OpenAPI schema for the Ceres Rest API.
    """
    from ceres.internal.app.main import App

    app = App(Engine(Config()))
    schema = app.openapi()

    match format:
        case OpenAPISchemaFormat.yaml:
            text = yamlify(schema, indent=indent)
        case OpenAPISchemaFormat.json:
            text = jsonify(schema, indent=indent)

    if output is not None:
        output.write_text(text)
    else:
        sys.stdout.write(text)
