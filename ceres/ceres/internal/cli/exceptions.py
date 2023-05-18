from click import ClickException as CLIException


class CLIInvalidConfigException(CLIException):
    exit_code = 1


class CLIDatabaseUnreachableException(CLIException):
    exit_code = 2


class CLICheckFailedException(CLIException):
    exit_code = 3


class CLIStartupException(CLIException):
    exit_code = 4


class CLIServerNotEnabledException(CLIException):
    exit_code = 5


class CLIEngineNotRunningException(CLIException):
    exit_code = 6


class CLIServiceConfigException(CLIException):
    exit_code = 7
