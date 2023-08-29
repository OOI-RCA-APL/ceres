from collections import defaultdict
from typing import TYPE_CHECKING, Iterable

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
    from ceres.component import ProcedureKind as ProcedureKind
    from ceres.component import action as action
    from ceres.component import on as on
    from ceres.component import query as query
    from ceres.component import routine as routine
else:
    __export("ceres.component", ["Component", "ProcedureKind", "action", "on", "query", "routine"])

if TYPE_CHECKING:
    from ceres.config import Config as Config
    from ceres.config import ConfigCheckKind as ConfigCheckKind
else:
    __export("ceres.config", ["Config", "ConfigCheckKind"])


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
    from ceres.database.database import Statistics as Statistics
    from ceres.database.enums import DatabaseKind as DatabaseKind
else:
    __export("ceres.database.database", ["Database", "Statistics", "DatabaseKind"])

if TYPE_CHECKING:
    from ceres.directory import Directory as Directory
else:
    __export("ceres.directory", ["Directory"])

if TYPE_CHECKING:
    from ceres.events import Event as Event
    from ceres.events import StandardEvent as StandardEvent
    from ceres.events import StandardEventKind as StandardEventKind
else:
    __export("ceres.events", ["Event", "StandardEvent", "StandardEventKind"])

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
    from ceres.roles.connection import ConnectionState as ConnectionState
else:
    __export("ceres.roles.connection", ["Connection", "ConnectionState"])

if TYPE_CHECKING:
    from ceres.roles.dispatcher import Dispatch as Dispatch
    from ceres.roles.dispatcher import Dispatcher as Dispatcher
    from ceres.roles.dispatcher import DispatchWriter as DispatchWriter
else:
    __export("ceres.roles.dispatcher", ["Dispatch", "Dispatcher", "DispatchWriter"])

if TYPE_CHECKING:
    from ceres.roles.notifier import Notification as Notification
    from ceres.roles.notifier import Notifier as Notifier
else:
    __export("ceres.roles.notifier", ["Notification", "Notifier"])

if TYPE_CHECKING:
    from ceres.roles.ui import UI as UI
else:
    __export("ceres.roles.ui", ["UI"])

if TYPE_CHECKING:
    from ceres.schedule import Schedule as Schedule
    from ceres.schedule import ScheduleKind as ScheduleKind
else:
    __export("ceres.schedule", ["Schedule", "ScheduleKind"])

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
