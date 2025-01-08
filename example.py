# File: example.py

from pydantic_settings import BaseSettings, CliPositionalArg, SettingsConfigDict


class Main(BaseSettings):
    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_enforce_required=True,
    )

    values: CliPositionalArg[list[str]] = []


# parsed = Main()
# print(parsed)

# # Output when running as `python example.py`:
# # usage: that.py [-h] VALUES
# # example.py: error: the following arguments are required: VALUES

# File: example.py

# from pydantic_settings import BaseSettings, CliPositionalArg, SettingsConfigDict


# class Main(BaseSettings):
#     model_config = SettingsConfigDict(
#         cli_parse_args=True,
#         cli_enforce_required=True,
#     )

#     values: CliPositionalArg[list[str]] = []


# parsed = Main()
# print(parsed)

# # Output when running as `python example.py`:
# # usage: that.py [-h] VALUES
# # example.py: error: the following arguments are required: VALUES
