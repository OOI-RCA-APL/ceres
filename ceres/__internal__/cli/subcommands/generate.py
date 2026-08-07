import sys
from typing import override

from pydantic import FilePath, NewPath, NonNegativeInt
from pydantic_settings import CliSubCommand

from ceres.__internal__.cli.shared import CLICommand, CLICommandGroup
from ceres.data import StrEnum, to_json, to_yaml


class OpenAPISchemaFormat(StrEnum):
    """Supported output formats for the OpenAPI schema."""

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
        """Generate the OpenAPI schema and write it to a file or stdout."""
        from ceres.__internal__.core import openapi_schema
        from ceres.data import from_json
        from ceres.version import __version__

        schema = from_json(openapi_schema(__version__))

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
