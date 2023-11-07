from collections import defaultdict
from typing import TYPE_CHECKING, Iterable

from ceres.version import __version__ as __version__

__exports: defaultdict[str, list[str]] = defaultdict(list)


def __export(path: str, names: Iterable[str]) -> None:
    __exports[path].extend(names)


if TYPE_CHECKING:
    from ceres.address import Address as Address
    from ceres.address import AddressSelector as AddressSelector
    from ceres.address import DynamicAddress as DynamicAddress
else:
    __export("ceres.address", ["Address", "AddressSelector", "DynamicAddress"])

if TYPE_CHECKING:
    from ceres.alert import Alert as Alert
else:
    __export("ceres.alert", ["Alert"])


if TYPE_CHECKING:
    from ceres.component import Component as Component
    from ceres.component import ProcedureType as ProcedureType
    from ceres.component import action as action
    from ceres.component import on as on
    from ceres.component import query as query
    from ceres.component import routine as routine
else:
    __export("ceres.component", ["Component", "ProcedureType", "action", "on", "query", "routine"])

if TYPE_CHECKING:
    from ceres.connectivity import Connectivity as Connectivity
else:
    __export("ceres.connectivity", ["Connectivity"])

if TYPE_CHECKING:
    from ceres.config import Config as Config
    from ceres.config import ConfigCheckType as ConfigCheckType
else:
    __export("ceres.config", ["Config", "ConfigCheckType"])


if TYPE_CHECKING:
    from ceres.data import DataObject as DataObject
    from ceres.data import ImmutableDataObject as ImmutableDataObject
    from ceres.data import ValidatedDataclass as ValidatedDataclass
    from ceres.data import jsonify as jsonify
    from ceres.data import simplify as simplify
else:
    __export(
        "ceres.data",
        ["DataObject", "ImmutableDataObject", "ValidatedDataclass", "jsonify", "simplify"],
    )

if TYPE_CHECKING:
    from ceres.database.database import Database as Database
else:
    __export("ceres.database.database", ["Database"])

if TYPE_CHECKING:
    from ceres.database.enums import DatabaseType as DatabaseType
    from ceres.database.enums import DataFormat as DataFormat
    from ceres.database.enums import ItemType as ItemType
else:
    __export("ceres.database.enums", ["DatabaseType", "DataFormat", "ItemType"])

if TYPE_CHECKING:
    from ceres.directory import Directory as Directory
else:
    __export("ceres.directory", ["Directory"])

if TYPE_CHECKING:
    from ceres.events import Event as Event
    from ceres.events import StandardEvent as StandardEvent
    from ceres.events import StandardEventType as StandardEventType
else:
    __export("ceres.events", ["Event", "StandardEvent", "StandardEventType"])

if TYPE_CHECKING:
    from ceres.exceptions import ParseException as ParseException
else:
    __export("ceres.exceptions", ["ParseException"])

if TYPE_CHECKING:
    from ceres.filter import AlertFilter as AlertFilter
    from ceres.filter import AlertOrder as AlertOrder
    from ceres.filter import ComponentFilter as ComponentFilter
    from ceres.filter import LogEntryFilter as LogEntryFilter
    from ceres.filter import LogEntryOrder as LogEntryOrder
    from ceres.filter import MessageFilter as MessageFilter
    from ceres.filter import MessageOrder as MessageOrder
    from ceres.filter import StatisticsFilter as StatisticsFilter
else:
    __export(
        "ceres.filter",
        [
            "AlertFilter",
            "AlertOrder",
            "ComponentFilter",
            "LogEntryFilter",
            "LogEntryOrder",
            "MessageFilter",
            "MessageOrder",
            "StatisticsFilter",
        ],
    )

if TYPE_CHECKING:
    from ceres.internal.cli import main as main
else:
    __export("ceres.internal.cli", ["main"])

if TYPE_CHECKING:
    from ceres.level import Level as Level
else:
    __export("ceres.level", ["Level"])

if TYPE_CHECKING:
    from ceres.loaded import Loaded as Loaded
    from ceres.loaded import Loader as Loader
else:
    __export("ceres.loaded", ["Loaded", "Loader"])

if TYPE_CHECKING:
    from ceres.message import Message as Message
    from ceres.message import MessageDirection as MessageDirection
else:
    __export("ceres.message", ["Message", "MessageDirection"])

if TYPE_CHECKING:
    from ceres.object import Status as Status
else:
    __export("ceres.object", ["Status"])

if TYPE_CHECKING:
    from ceres.parsing import Parser as Parser
else:
    __export("ceres.parsing", ["Parser"])

if TYPE_CHECKING:
    from ceres.reference import Ref as Ref
    from ceres.reference import Reference as Reference
else:
    __export("ceres.reference", ["Ref", "Reference"])

if TYPE_CHECKING:
    from ceres.result import Fail as Fail
    from ceres.result import Ok as Ok
    from ceres.result import Result as Result
else:
    __export("ceres.result", ["Fail", "Ok", "Result"])

if TYPE_CHECKING:
    from ceres.roles.connection import Connection as Connection
    from ceres.roles.connection import TCPConnection as TCPConnection
else:
    __export("ceres.roles.connection", ["Connection", "TCPConnection"])

if TYPE_CHECKING:
    from ceres.roles.dispatcher import Dispatch as Dispatch
    from ceres.roles.dispatcher import Dispatcher as Dispatcher
    from ceres.roles.dispatcher import DispatchWriter as DispatchWriter
    from ceres.roles.dispatcher import HTMLDispatchWriter as HTMLDispatchWriter
else:
    __export(
        "ceres.roles.dispatcher", ["Dispatch", "Dispatcher", "DispatchWriter", "HTMLDispatchWriter"]
    )

if TYPE_CHECKING:
    from ceres.roles.interface import Interface as Interface
else:
    __export("ceres.roles.interface", ["Interface"])

if TYPE_CHECKING:
    from ceres.roles.notifier import Notification as Notification
    from ceres.roles.notifier import Notifier as Notifier
    from ceres.roles.notifier import SMTPNotifier as SMTPNotifier
else:
    __export("ceres.roles.notifier", ["Notification", "Notifier", "SMTPNotifier"])

if TYPE_CHECKING:
    from ceres.roles.interface import Interface as Interface
else:
    __export("ceres.roles.interface", ["Interface"])

if TYPE_CHECKING:
    from ceres.schedule import Schedule as Schedule
    from ceres.schedule import ScheduleType as ScheduleType
else:
    __export("ceres.schedule", ["Schedule", "ScheduleType"])

if TYPE_CHECKING:
    from ceres.statistics import Statistics as Statistics
else:
    __export("ceres.statistics", ["Statistics"])

if TYPE_CHECKING:
    from ceres.stream import Stream as Stream
    from ceres.stream import StreamReader as StreamReader
    from ceres.stream import WriteStream as WriteStream
else:
    __export("ceres.stream", ["Stream", "StreamReader", "WriteStream"])

if TYPE_CHECKING:
    from ceres.threading import spawn as spawn
else:
    __export("ceres.threading", ["spawn"])

if TYPE_CHECKING:
    from ceres.timing import utc as utc
else:
    __export("ceres.timing", ["utc"])

__export_mapping: dict[str, str] = {}


def __init_export_mapping() -> None:
    for path, names in __exports.items():
        for name in names:
            __export_mapping[name] = path


__init_export_mapping()


def __getattr__(name: str) -> object:
    path = __export_mapping.get(name)
    if path is None:
        raise AttributeError(f"module {__name__} has no attribute {name}")

    from importlib import import_module

    module = import_module(path, package=__package__)
    return getattr(module, name)


if not TYPE_CHECKING:
    __all__ = sorted(__export_mapping.keys())
