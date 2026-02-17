from __future__ import annotations

import sys
from typing import override

from pydantic import FilePath, NewPath, NonNegativeInt
from pydantic_settings import CliSubCommand

from ceres._internal.cli.shared import CLICommand, CLICommandGroup
from ceres.data import StrEnum, to_json, to_yaml


class OpenAPISchemaFormat(StrEnum):
    YAML = "yaml"
    JSON = "json"


class OpenApiCommand(CLICommand):
    """
    Generate up-to-date OpenAPI schema for the Ceres Rest API.
    """

    output: FilePath | NewPath | None = None
    """File path to write to. If omitted, standard output is used."""
    format: OpenAPISchemaFormat = OpenAPISchemaFormat.YAML
    """Specify the output file format."""
    indent: NonNegativeInt = 2
    """Specify indentation size of output."""

    @override
    async def __run__(self) -> None:
        from ceres._internal.app.main import App
        from ceres.engine import Engine

        app = App(Engine())
        schema = app.openapi()

        match self.format:
            case OpenAPISchemaFormat.YAML:
                text = to_yaml(schema, indent=self.indent)
            case OpenAPISchemaFormat.JSON:
                text = to_json(schema, indent=self.indent)

        if self.output is not None:
            self.output.write_text(text)
        else:
            sys.stdout.write(text)


class GenerateCommand(CLICommandGroup):
    """
    Generate various project resources.
    """

    openapi: CliSubCommand[OpenApiCommand]
