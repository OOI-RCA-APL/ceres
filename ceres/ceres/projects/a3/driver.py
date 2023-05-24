import asyncio
import json
import os
import random
import re
import traceback
from asyncio import Lock as AsyncLock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence, cast

import numpy as np
from pydantic import Field
from typing_extensions import override

if TYPE_CHECKING:
    nc: Any
    Dataset: Any
else:
    import netCDF4 as nc
    from netCDF4 import Dataset

from ceres.alert import Level
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.events import MessageReceivedEvent, MessageSentEvent
from ceres.exceptions import ParseException
from ceres.internal.utilities import BytesLike, bytes_of
from ceres.listener import on
from ceres.message import Message, MessageDirection
from ceres.procedure import action
from ceres.projects.a3.parsing import (
    BaseDASAZAResponse,
    DASAZAResponse,
    DASAZSResponse,
    DASLoggedDQZMessage,
    DASLoggedINCMessage,
    DASLoggedMessage,
    DASLoggedPRSMessage,
    DASLoggedTIMMessage,
    DASLoggedTMPMessage,
    DASMessageInfo,
    HostCSResponse,
    HostSENSResponse,
    HostSIResponse,
    parse_logged_das_message,
)
from ceres.ref import Ref
from ceres.roles.alerter import Alerter
from ceres.roles.connection import Connection
from ceres.threading import spawn
from ceres.timing import utc
from ceres.transport import Transport


class JobIncomplete(ImmutableDataObject):
    message: str


class NodeDefinition(ImmutableDataObject):
    name: str
    address: int
    wired: bool = False


class HostSettings(ImmutableDataObject):
    connection: Ref[Connection]


class DASSettings(ImmutableDataObject):
    id: int
    connection: Ref[Connection]
    sampling_interval: PositiveTimeDelta = timedelta(minutes=1)


class RemoteScienceDataCollection(ImmutableDataObject):
    start_time: datetime
    end_time: datetime
    sens: Mapping[int, HostSENSResponse]
    si: Mapping[int, HostSIResponse]
    cs: Mapping[int, HostCSResponse]


class LocalScienceDataCollection(ImmutableDataObject):
    tim: DASLoggedTIMMessage
    tmp: DASLoggedTMPMessage
    inc: DASLoggedINCMessage
    dqz: DASLoggedDQZMessage
    prs: DASLoggedPRSMessage


class AZACollection(ImmutableDataObject):
    start_time: datetime
    end_time: datetime
    start_azs: DASAZSResponse
    start_high_pressure_aza: DASAZAResponse
    low_pressure_aza: DASAZAResponse
    end_high_pressure_aza: DASAZAResponse
    end_azs: DASAZSResponse

    @property
    def responses(self) -> Sequence[BaseDASAZAResponse]:
        return [
            self.start_azs,
            self.start_high_pressure_aza,
            self.low_pressure_aza,
            self.end_high_pressure_aza,
            self.end_azs,
        ]


class A3Driver(Alerter):
    host: HostSettings
    das: DASSettings
    nodes: Sequence[NodeDefinition] = Field(default_factory=list)

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__job_lock = AsyncLock()
        self.__last_sequence_number: int | None = None

    @on(MessageSentEvent, ["host.connection", "das.connection"])
    def __on_message_sent(self, event: MessageSentEvent) -> None:
        self.log.info(f"Sent: {event.message}")

    @on(MessageReceivedEvent, ["host.connection", "das.connection"])
    def __on_message_received(self, event: MessageReceivedEvent) -> None:
        self.log.info(f"Received: {event.message}")

    async def __use_job_lock(self, priority: int, message: str | None = None) -> AsyncLock:
        await asyncio.sleep(priority * 0.1)
        if self.__job_lock.locked():
            if message is not None:
                self.log.info(message)
            return self.__job_lock

        return self.__job_lock

    def __job_incomplete(self, message: str) -> JobIncomplete:
        self.log.error(message)
        return JobIncomplete(message=message)

    @action
    async def collect_remote_science_data(self) -> JobIncomplete | None:
        async with await self.__use_job_lock(
            1, "Waiting for other job to finish before running science collection job..."
        ):
            transport = Transport(self.host.connection)
            self.log.info("Running science collection job...")
            if not self.host.connection.connected:
                return self.__job_incomplete(
                    "No host connection is active to run the science collection job."
                )

            # Wait a bit before the job starts.
            await asyncio.sleep(3)

            for node in self.nodes:
                # Send a 'SENS' command once to warm up the sensors, then send it again after a few
                # seconds to get updated data.
                for i in range(2):
                    command = "<SENS" if node.wired else f"<SENS:{node.address};W1"

                    # Send the command and wait for a response.
                    await self.__send_host("sens", command.encode(), b">SENS")

                    # Delay after sending the first command.
                    if i == 0:
                        await asyncio.sleep(10)

                # Get the addresses of the other nodes in the array.
                addresses = [
                    current.address for current in self.nodes if current.address is not node.address
                ]

                # If there are no other addresses, ignore.
                if not addresses:
                    continue

                # Send an 'SI' command of the form...
                # Local (2501): <SI:CI1,INT1,WKT1,IR2502,IR2503,IR2504
                # Remote (2502): <SI:2502;W1,CI1,INT1,WKT1,IR2501,IR2503,IR2504

                # CI1: Set common interrogation signal to 1.
                # INT1: Use 1 interrogation cycle.
                # WKT1: Set the wake-up tone to 1.
                if node.wired:
                    command = "<SI:CI1,INT1,WKT1"
                else:
                    command = f"<SI:{node.address};W1,CI1,INT1,WKT1"

                # Add addresses of neighboring nodes to range to.
                command += ","
                command += ",".join(f"IR{address}" for address in addresses)

                # Send the command.
                # TODO: Re-enable retries when we've sufficiently debugged ranging issues.
                await transport.send(">SI")

        self.log.info("Science data collection job completed successfully.")
        return None

    @action
    async def collect_configuration_statuses(self) -> JobIncomplete | None:
        if not self.host.connection or not self.host.connection.connected:
            return self.__job_incomplete(
                "No host connection is active to run the configuration status collection job."
            )

        self.log.info("Running configuration status collection job...")
        async with await self.__use_job_lock(
            2,
            "Waiting for other job to finish before running configuration status collection job...",
        ):
            # Wait a bit before the job starts.
            await asyncio.sleep(3)

            # For each node, send a 'CS' command to get configuration status information.
            for node in self.nodes:
                if node.wired:
                    command = b"<CS"
                else:
                    command = f"<CS:{node.address};W1".encode()

                await self.__send_host("cs", command, b">CS")

        self.log.info("Configuration status collection job completed successfully.")
        return None

    @action
    async def collect_volatile_statuses(self) -> JobIncomplete | None:
        if not self.host.connection or not self.host.connection.connected:
            return self.__job_incomplete(
                "No host connection is active to run the collect volatile statuses job."
            )

        async with await self.__use_job_lock(
            3,
            "Waiting for other job to finish before running volatile status collection job...",
        ):
            # Wait a bit before the job starts.
            await asyncio.sleep(3)

            # For each node, send a 'VS' command to get volatile status information.
            for node in self.nodes:
                if node.wired:
                    command = b"<VS"
                else:
                    command = f"<VS:{node.address};W1".encode()

                await self.__send_host("vs", command, b">VS")

        self.log.info("Volatile status collection job completed successfully.")
        return None

    @action
    async def sync_host(self) -> JobIncomplete | None:
        if not self.host.connection or not self.host.connection.connected:
            return self.__job_incomplete(
                "No host connection is active to run the collect volatile statuses job."
            )

        async with await self.__use_job_lock(
            3,
            "Waiting for other job to finish before running sync host job...",
        ):
            self.log.info("Running sync host job...")
            # Wait a bit before the job starts.
            await asyncio.sleep(3)

            # For the wired node, send a '<TIME' command to set the current time.
            for node in self.nodes:
                if not node.wired:
                    continue

                now = utc()
                time = now.strftime("%H.%M.%S;%d/%m/%y")

                # Send the command.
                await self.__send_host("time", f"<TIME:TD{time}".encode(), b">TIME")

            # For the non-wired nodes, send a '<TSYNC' command to time sync with the wired unit.
            for node in self.nodes:
                if node.wired:
                    continue

                # Send the command.
                # SET: Actually set the time on the remote node rather than just computing offsets.
                await self.__send_host(
                    "tsync",
                    f"<TSYNC:{node.address};W1,SET".encode(),
                    b">TSYNC",
                )

        self.log.info("Sync host job completed successfully.")
        return None

    async def sync_das(self) -> JobIncomplete | None:
        if not self.das.connection or not self.das.connection.connected:
            return self.__job_incomplete("No DAS connection is active to run the sync DAS job.")

        def format_time(time: datetime) -> str:
            return time.strftime("%d%m%y06%H%M%S")

        async with await self.__use_job_lock(
            5,
            "Waiting for other job to finish before running sync DAS job...",
        ):
            self.log.info("Running sync DAS job...")

            # Wait a bit before the job starts.
            await asyncio.sleep(3)

            self.log.info("Stopping DAS logging temporarily...")
            # Send an '@LGEN' command with -1 as the first argument to stop all logging.
            await self.__send_das("lgen", f"@LGEN${self.das.id},?&,-1".encode(), b"%LGST")

            # Wait a bit before syncing time.
            await asyncio.sleep(3)

            self.log.info("Syncing DAS time...")

            # Send a '<@STDT' command to set the current time.
            time = format_time(utc())
            await self.__send_das(
                "stdt",
                f"<@STDT${self.das.id},?&,{time}".encode(),
                b"%STSY",
            )

            # Wait a bit before syncing the logging configuration.
            await asyncio.sleep(3)

            self.log.info("Syncing DAS logging configuration...")
            # Send an '@LGBG' command to start logging 3 minutes from now. The start time must be at
            # least two minutes ahead of the current time.
            start = format_time(datetime.now(timezone.utc) + timedelta(minutes=3))
            seconds = int(self.das.sampling_interval.total_seconds())
            await self.__send_das(
                "lgbg",
                f"@LGBG${self.das.id},?&;1,{start},{seconds},0,29,0.00,0,0".encode(),  # noqa: E501
                b"%LGST",
            )

        self.log.info("Sync DAS job completed successfully.")
        return None

    @action
    async def export_data(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> JobIncomplete | None:
        now = utc()

        if start is None:
            start = now.date() - timedelta(days=1)
        if end is None:
            end = start + timedelta(days=1)
        if end < start:
            start, end = end, start

        exceptions: list[Exception] = []

        async with await self.__use_job_lock(
            7,
            "Waiting for other job to finish before running export job...",
        ):
            self.log.info("Running export job...")

            day = start

            while day <= end:
                start_timestamp = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
                end_timestamp = start_timestamp + timedelta(days=1)

                try:
                    await self.export_remote_science_data(start_timestamp, end_timestamp)
                except Exception as exception:
                    exceptions.append(exception)
                    self.log.error(
                        f"Remote science data export raised an exception: {traceback.format_exc()}"
                    )

                try:
                    await self.export_local_science_data(start_timestamp, end_timestamp)
                except Exception as exception:
                    exceptions.append(exception)
                    self.log.error(
                        f"Local science data export raised an exception: {traceback.format_exc()}"
                    )

                day += timedelta(days=1)

            try:
                await self.export_aza_data()
            except Exception as exception:
                exceptions.append(exception)
                self.log.error(f"AZA data export raised an exception: {traceback.format_exc()}")

        if exceptions:
            raise exceptions[0]

        self.log.info("Export job completed successfully.")
        return None

    @action
    async def export_remote_science_data(
        self,
        start: DateTime,
        end: DateTime,
    ) -> None:
        self.log.info(f"Exporting remote science data for [{start.date().isoformat()}]...")
        collections = await self.extract_remote_science_data_collections(start, end)

        if collections:
            path = await spawn(
                lambda: self.write_remote_science_data_collections(
                    date=start.date(),
                    collections=collections,
                )
            )

            self.log.info(f"Created: {path}")
        else:
            self.log.info(f"No remote science data to export for [{start.date().isoformat()}].")

    @action
    async def extract_remote_science_data_collections(
        self,
        start: DateTime,
        end: DateTime,
    ) -> Sequence[RemoteScienceDataCollection]:
        wired = next((node for node in self.nodes if node.wired), None)
        collections: list[RemoteScienceDataCollection] = []

        if not wired:
            return collections

        initiators = await self.environment.get_messages(
            address=self.host.connection.address,
            after=start,
            before=end,
            direction=MessageDirection.SEND,
            prefix=b"<SENS\r\n",
        )

        for initiator in initiators:
            # Try to find a second SENS command shortly after the first.
            second = await self.environment.get_message(
                address=self.host.connection.address,
                after=initiator.timestamp,
                before=initiator.timestamp + timedelta(minutes=1),
                direction=MessageDirection.SEND,
                prefix=b"<SENS\r\n",
            )

            # If there is no second command, this is probably not a valid initiator message.
            if not second:
                continue

            sens_response_messages = await self.environment.get_messages(
                address=self.host.connection.address,
                after=initiator.timestamp,
                before=initiator.timestamp + timedelta(minutes=10),
                direction=MessageDirection.RECEIVE,
                prefix=b">SENS",
            )

            si_response_messages = await self.environment.get_messages(
                address=self.host.connection.address,
                after=initiator.timestamp,
                before=initiator.timestamp + timedelta(minutes=10),
                direction=MessageDirection.RECEIVE,
                prefix=b">SI",
            )

            sens_responses = _get_best_sens_responses(sens_response_messages)
            si_responses = _get_best_si_responses(si_response_messages)
            if not sens_responses or not si_responses:
                continue

            addresses = sorted({*sens_responses.keys(), *si_responses.keys()})
            responses = [*sens_responses.values(), *si_responses.values()]

            start_time = min(response.source.timestamp for response in responses)
            end_time = max(response.source.timestamp for response in responses)

            cs_responses: dict[int, HostCSResponse] = {}

            for address in addresses:
                cs_response_message = await self.environment.get_message(
                    address=self.host.connection.address,
                    before=initiator.timestamp,
                    direction=MessageDirection.RECEIVE,
                    prefix=f">CS:{address}".encode(),
                )

                if cs_response_message:
                    try:
                        cs_responses[address] = HostCSResponse.parse(cs_response_message)
                    except ParseException:
                        pass

            collections.append(
                RemoteScienceDataCollection(
                    start_time=start_time,
                    end_time=end_time,
                    sens=sens_responses,
                    si=si_responses,
                    cs=cs_responses,
                )
            )

        return collections

    def write_remote_science_data_collections(
        self,
        date: date,
        collections: Sequence[RemoteScienceDataCollection],
    ) -> Path:
        if not collections:
            raise Exception("No collections to export.")

        directory = self.paths.data.subdir(f"/science/{date.year}/{date.month}")
        directory.create()
        path = directory / f"{date.isoformat()}.remote.nc"

        address_set: set[int] = set()

        for result in collections:
            address_set |= result.sens.keys()
            address_set |= result.si.keys()

        addresses = sorted(address_set)

        # Create dataset.
        with Dataset(path, "w", format="NETCDF4") as dataset:
            dataset.title = "Science Data"

            # Create dimensions.
            dataset.createDimension("address", len(addresses))
            dataset.createDimension("time", None)

            #
            # Create common variables.
            #

            # Create node acoustic address variable.
            address_variable = dataset.createVariable("address", np.int64, ["address"])
            address_variable.standard_name = "address"
            address_variable.long_name = "Node Acoustic Address"

            # Add node acoustic addresses.
            address_variable[:] = np.array(addresses, np.int64)

            # Create time variable.
            time_variable = dataset.createVariable("time", np.int64, ["time"])
            time_variable.units = TIMESTAMP_UNITS
            time_variable.standard_name = "time"
            time_variable.long_name = "Time"

            # Add time data.
            time_variable[:] = nc.date2num(
                [collection.start_time for collection in collections], TIMESTAMP_UNITS
            )

            #
            # Create SENS data variables.
            #

            # Create incline pitch variable.
            pitch_variable = dataset.createVariable("pitch", np.float64, ["address", "time"])
            pitch_variable.units = "degrees"
            pitch_variable.standard_name = "pitch"
            pitch_variable.long_name = "Pitch"

            # Create incline roll variable.
            roll_variable = dataset.createVariable("roll", np.float64, ["address", "time"])
            roll_variable.units = "degrees"
            roll_variable.standard_name = "roll"
            roll_variable.long_name = "Roll"

            # Create temperature variable.
            temperature_variable = dataset.createVariable(
                "temperature", np.float64, ["address", "time"]
            )
            temperature_variable.units = "degrees C"
            temperature_variable.standard_name = "temperature"
            temperature_variable.long_name = "Temperature"

            # Create sound velocity variable.
            sound_velocity_variable = dataset.createVariable(
                "sound_velocity", np.float64, ["address", "time"]
            )
            sound_velocity_variable.units = "meters/second"
            sound_velocity_variable.standard_name = "sound_velocity"
            sound_velocity_variable.long_name = "Sound Velocity"

            # Create pressure variable.
            pressure_variable = dataset.createVariable("pressure", np.float64, ["address", "time"])
            pressure_variable.units = "kPa"
            pressure_variable.standard_name = "pressure"
            pressure_variable.long_name = "Pressure"

            # Create secondary pressure variable.
            secondary_pressure_variable = dataset.createVariable(
                "secondary_pressure", np.float64, ["address", "time"]
            )
            secondary_pressure_variable.units = "kPa"
            secondary_pressure_variable.standard_name = "secondary_pressure"
            secondary_pressure_variable.long_name = "Secondary Pressure"

            # Add SENS response data to variables.
            for i, address in enumerate(addresses):
                for j, collection in enumerate(collections):
                    sens = collection.sens.get(address)
                    if not sens:
                        continue

                    pitch_variable[i, j] = sens.pitch
                    roll_variable[i, j] = sens.roll
                    temperature_variable[i, j] = sens.temperature
                    sound_velocity_variable[i, j] = sens.sound_velocity
                    pressure_variable[i, j] = sens.pressure
                    secondary_pressure_variable[i, j] = sens.secondary_pressure

            #
            # Create SI data variables.
            #

            # Create range delay variable.
            range_delay_variable = dataset.createVariable(
                "range_delay",
                np.float64,
                [
                    "address",  # The address of the node doing the ranging.
                    "address",  # The address of remote node being ranged to.
                    "time",
                ],
            )
            range_delay_variable.units = "microseconds"
            range_delay_variable.standard_name = "range_delay"
            range_delay_variable.long_name = "Range Delay"

            # Add SI response data to variables.
            for i, address in enumerate(addresses):
                for j, remote_address in enumerate(addresses):
                    for k, collection in enumerate(collections):
                        si = collection.si.get(address)
                        if not si:
                            continue

                        range_delay = si.range_delays.get(remote_address, np.nan)
                        range_delay_variable[i, j, k] = range_delay

            #
            # Create all CS variables.
            #

            # Create turn-around-time variable.
            turn_around_time_variable = dataset.createVariable(
                "turn_around_time", np.float64, ["address", "time"]
            )
            turn_around_time_variable.units = "milliseconds"
            turn_around_time_variable.standard_name = "turn_around_time"
            turn_around_time_variable.long_name = "Turn Around Time"

            # Add CS response data to variables.
            for i, address in enumerate(addresses):
                for j, collection in enumerate(collections):
                    cs = collection.cs.get(address)
                    if not cs:
                        continue

                    turn_around_time_variable[i, j] = cs.turn_around_time

            #
            # Create response timestamp variables.
            #

            # Create SENS response timestamp variable.
            sens_response_timestamp_variable = dataset.createVariable(
                "sens_response_timestamp", np.int64, ["address", "time"]
            )
            sens_response_timestamp_variable.units = TIMESTAMP_UNITS
            sens_response_timestamp_variable.standard_name = "sens_response_timestamp"
            sens_response_timestamp_variable.long_name = "SENS Response Timestamp"

            # Create SI response timestamp variable.
            si_response_timestamp_variable = dataset.createVariable(
                "si_response_timestamp", np.int64, ["address", "time"]
            )
            si_response_timestamp_variable.units = TIMESTAMP_UNITS
            si_response_timestamp_variable.standard_name = "si_response_timestamp"
            si_response_timestamp_variable.long_name = "SI Response Timestamp"

            # Create CS response timestamp variable.
            cs_response_timestamp_variable = dataset.createVariable(
                "cs_response_timestamp", np.int64, ["address", "time"]
            )
            cs_response_timestamp_variable.units = TIMESTAMP_UNITS
            cs_response_timestamp_variable.standard_name = "cs_response_timestamp"
            cs_response_timestamp_variable.long_name = "CS Response Timestamp"

            # Add response timestamp data to variables.
            for i, address in enumerate(addresses):
                for j, collection in enumerate(collections):
                    if sens := collection.sens.get(address):
                        sens_response_timestamp_variable[i, j] = nc.date2num(
                            sens.source.timestamp, TIMESTAMP_UNITS
                        )
                    if si := collection.si.get(address):
                        si_response_timestamp_variable[i, j] = nc.date2num(
                            si.source.timestamp, TIMESTAMP_UNITS
                        )
                    if cs := collection.cs.get(address):
                        cs_response_timestamp_variable[i, j] = nc.date2num(
                            cs.source.timestamp, TIMESTAMP_UNITS
                        )

        return path

    @action
    async def export_local_science_data(self, start: datetime, end: datetime) -> None:
        self.log.info(f"Exporting local science data for [{start.date().isoformat()}]...")
        collections = await self.extract_local_science_data_collections(start, end)

        if collections:
            path = await spawn(
                lambda: self.write_local_science_data_collections(
                    date=start.date(),
                    collections=collections,
                )
            )

            self.log.info(f"Created: {path}")
        else:
            self.log.info(f"No local science data to export for [{start.date().isoformat()}].")

    @action
    async def extract_local_science_data_collections(
        self,
        start: DateTime,
        end: DateTime,
    ) -> list[LocalScienceDataCollection]:
        collections: list[LocalScienceDataCollection] = []

        messages = await self.environment.get_messages(
            address=self.das.connection.address,
            after=start,
            before=end,
            direction=MessageDirection.RECEIVE,
            regex=re.compile(rb"^%[0-9]+,.+$"),
        )

        latest: dict[type[DASLoggedMessage], DASLoggedMessage] = {}

        for message in messages:
            try:
                parsed = parse_logged_das_message(message)
            except ParseException:
                continue

            latest[type(parsed)] = parsed

            if isinstance(parsed, DASLoggedPRSMessage):
                tim = cast(DASLoggedTIMMessage | None, latest.get(DASLoggedTIMMessage))
                tmp = cast(DASLoggedTMPMessage | None, latest.get(DASLoggedTMPMessage))
                inc = cast(DASLoggedINCMessage | None, latest.get(DASLoggedINCMessage))
                dqz = cast(DASLoggedDQZMessage | None, latest.get(DASLoggedDQZMessage))
                prs = cast(DASLoggedPRSMessage | None, latest.get(DASLoggedPRSMessage))
            else:
                continue

            if not tim or not tmp or not inc or not dqz or not prs:
                continue

            collections.append(
                LocalScienceDataCollection(
                    tim=tim,
                    tmp=tmp,
                    inc=inc,
                    dqz=dqz,
                    prs=prs,
                )
            )

        return collections

    def write_local_science_data_collections(
        self,
        date: date,
        collections: Sequence[LocalScienceDataCollection],
    ) -> Path:
        if not collections:
            raise Exception("No collections to export.")

        directory = self.paths.data.subdir(f"/science/{date.year}/{date.month}")
        directory.create()
        path = directory / f"{date.isoformat()}.local.nc"

        # Create dataset.
        with Dataset(str(path), "w", format="NETCDF4") as dataset:
            dataset.title = "Local Science Data"

            # Create dimensions.
            dataset.createDimension("time", None)

            #
            # Create common variables.
            #

            # Create time variable.
            time_variable = dataset.createVariable("time", np.int64, ["time"])
            time_variable.units = TIMESTAMP_UNITS
            time_variable.standard_name = "time"
            time_variable.long_name = "Time"

            # Add time data.
            time_variable[:] = nc.date2num(
                [collection.tim.source.timestamp for collection in collections], TIMESTAMP_UNITS
            )

            #
            # Create data variables.
            #

            # Create temperature variable.
            temperature_variable = dataset.createVariable("temperature", np.float64, ["time"])
            temperature_variable.units = "degrees C"
            temperature_variable.standard_name = "temperature"
            temperature_variable.long_name = "Temperature"

            # Create pitch variable.
            pitch_variable = dataset.createVariable("pitch", np.float64, ["time"])
            pitch_variable.units = "degrees"
            pitch_variable.standard_name = "pitch"
            pitch_variable.long_name = "Pitch"

            # Create roll variable.
            roll_variable = dataset.createVariable("roll", np.float64, ["time"])
            roll_variable.units = "degrees"
            roll_variable.standard_name = "roll"
            roll_variable.long_name = "Roll"

            # Create DQZ pressure variable.
            dqz_pressure_variable = dataset.createVariable("dqz_pressure", np.float64, ["time"])
            dqz_pressure_variable.units = "kPa"
            dqz_pressure_variable.standard_name = "dqz_pressure"
            dqz_pressure_variable.long_name = "DQZ Pressure"

            # Create DQZ temperature variable.
            dqz_temperature_variable = dataset.createVariable(
                "dqz_temperature", np.float64, ["time"]
            )
            dqz_temperature_variable.units = "degrees C"
            dqz_temperature_variable.standard_name = "dqz_temperature"
            dqz_temperature_variable.long_name = "DQZ Temperature"

            # Create PRS pressure variable.
            prs_pressure_variable = dataset.createVariable("prs_pressure", np.float64, ["time"])
            prs_pressure_variable.units = "kPa"
            prs_pressure_variable.standard_name = "prs_pressure"
            prs_pressure_variable.long_name = "PRS Pressure"

            # Create PRS temperature variable.
            prs_temperature_variable = dataset.createVariable(
                "prs_temperature", np.float64, ["time"]
            )
            prs_temperature_variable.units = "degrees C"
            prs_temperature_variable.standard_name = "prs_temperature"
            prs_temperature_variable.long_name = "PRS Temperature"

            #
            # Create message timestamp variables.
            #

            # Create TMP message timestamp variable.
            tmp_message_timestamp_variable = dataset.createVariable(
                "tmp_message_timestamp", np.int64, ["time"]
            )
            tmp_message_timestamp_variable.units = TIMESTAMP_UNITS
            tmp_message_timestamp_variable.standard_name = "tmp_message_timestamp"
            tmp_message_timestamp_variable.long_name = "TMP Message Timestamp"

            # Create INC message timestamp variable.
            inc_message_timestamp_variable = dataset.createVariable(
                "inc_message_timestamp", np.int64, ["time"]
            )
            inc_message_timestamp_variable.units = TIMESTAMP_UNITS
            inc_message_timestamp_variable.standard_name = "inc_message_timestamp"
            inc_message_timestamp_variable.long_name = "INC Message Timestamp"

            # Create DQZ message timestamp variable.
            dqz_message_timestamp_variable = dataset.createVariable(
                "dqz_message_timestamp", np.int64, ["time"]
            )
            dqz_message_timestamp_variable.units = TIMESTAMP_UNITS
            dqz_message_timestamp_variable.standard_name = "dqz_message_timestamp"
            dqz_message_timestamp_variable.long_name = "DQZ Message Timestamp"

            # Create PRS message timestamp variable.
            prs_message_timestamp_variable = dataset.createVariable(
                "prs_message_timestamp", np.int64, ["time"]
            )
            prs_message_timestamp_variable.units = TIMESTAMP_UNITS
            prs_message_timestamp_variable.standard_name = "prs_message_timestamp"
            prs_message_timestamp_variable.long_name = "PRS Message Timestamp"

            # Add data to variables.
            for i, collection in enumerate(collections):
                temperature_variable[i] = collection.tmp.temperature
                pitch_variable[i] = collection.inc.pitch
                roll_variable[i] = collection.inc.roll
                dqz_pressure_variable[i] = collection.dqz.pressure
                dqz_temperature_variable[i] = collection.dqz.temperature
                prs_pressure_variable[i] = collection.prs.pressure
                prs_temperature_variable[i] = collection.prs.temperature

                tmp_message_timestamp_variable[i] = nc.date2num(
                    collection.tmp.source.timestamp, TIMESTAMP_UNITS
                )
                inc_message_timestamp_variable[i] = nc.date2num(
                    collection.inc.source.timestamp, TIMESTAMP_UNITS
                )
                dqz_message_timestamp_variable[i] = nc.date2num(
                    collection.dqz.source.timestamp, TIMESTAMP_UNITS
                )
                prs_message_timestamp_variable[i] = nc.date2num(
                    collection.prs.source.timestamp, TIMESTAMP_UNITS
                )

        return path

    async def export_aza_data(self) -> None:
        self.log.info("Exporting AZA data...")
        collections = collections = await self.extract_aza_data_collections()
        if collections:
            await spawn(lambda: self.write_aza_data_collections(collections))
        else:
            self.log.info("No AZA data to export.")

    async def extract_aza_data_collections(self) -> list[AZACollection]:
        collections: list[AZACollection] = []

        commands = await self.environment.get_messages(
            address=self.das.connection.address,
            direction=MessageDirection.SEND,
            prefix=b"@AZAC",
            suffix=b",4\r\n",
        )

        for command in commands:
            messages = await self.environment.get_messages(
                address=self.das.connection.address,
                after=command.timestamp,
                before=command.timestamp + timedelta(minutes=10),
                regex=re.compile(b"^%[0-9]+,AZ[S,A],.*$"),
            )

            aszs: list[DASAZSResponse] = []
            asza: list[DASAZAResponse] = []

            for message in messages:
                try:
                    if b"AZS," in message.content:
                        aszs.append(DASAZSResponse.parse(message))
                    elif b"AZA," in message.content:
                        asza.append(DASAZAResponse.parse(message))
                except ParseException:
                    self.log.warning(f"Failed to parse AZA response: {traceback.format_exc()}")
                    continue

            if len(aszs) < 2 or len(asza) < 3:
                continue

            start_time = command.timestamp
            end_time = max(message.timestamp for message in messages)

            collection = AZACollection(
                start_time=start_time,
                end_time=end_time,
                start_azs=aszs[0],
                start_high_pressure_aza=asza[0],
                low_pressure_aza=asza[1],
                end_high_pressure_aza=asza[2],
                end_azs=aszs[1],
            )

            collections.append(collection)

        return collections

    def write_aza_data_collections(self, collections: Sequence[AZACollection]) -> Path:
        if not collections:
            raise Exception("No collections to export.")

        directory = self.paths.data
        directory.create()
        path = directory / "aza.nc"

        responses = list(range(1, 6))

        with Dataset(path, "w", format="NETCDF4") as dataset:
            # Create dimensions.
            dataset.createDimension("response", len(responses))
            dataset.createDimension("time", None)

            # Create response variable.
            response_variable = dataset.createVariable("response", np.int64, ["response"])
            response_variable.standard_name = "response"
            response_variable.long_name = "Response Number"

            # Add node acoustic addresses.
            response_variable[:] = np.array(responses, np.int64)

            # Create time variable.
            time_variable = dataset.createVariable("time", np.int64, ["time"])
            time_variable.units = TIMESTAMP_UNITS
            time_variable.standard_name = "time"
            time_variable.long_name = "Time"

            # Add time data.
            time_variable[:] = nc.date2num(
                [collection.start_time for collection in collections], TIMESTAMP_UNITS
            )

            #
            # Create all AZA variables.
            #

            # Create transfer sensor pressure variable.
            transfer_sensor_pressure_variable = dataset.createVariable(
                "transfer_sensor_pressure", np.float64, ["response", "time"]
            )
            transfer_sensor_pressure_variable.units = "KPa"
            transfer_sensor_pressure_variable.standard_name = "transfer_sensor_pressure"
            transfer_sensor_pressure_variable.long_name = "Transfer Sensor Pressure"

            # Create transfer sensor temperature variable.
            transfer_sensor_temperature_variable = dataset.createVariable(
                "transfer_sensor_temperature", np.float64, ["response", "time"]
            )
            transfer_sensor_temperature_variable.units = "degrees C"
            transfer_sensor_temperature_variable.standard_name = "transfer_sensor_temperature"
            transfer_sensor_temperature_variable.long_name = "Transfer Sensor Temperature"

            # Create ambient sensor pressure variable.
            ambient_sensor_pressure_variable = dataset.createVariable(
                "ambient_sensor_pressure", np.float64, ["response", "time"]
            )
            transfer_sensor_pressure_variable.units = "KPa"
            ambient_sensor_pressure_variable.standard_name = "ambient_sensor_pressure"
            ambient_sensor_pressure_variable.long_name = "Ambient Sensor Pressure"

            # Create ambient sensor temperature variable.
            ambient_sensor_temperature_variable = dataset.createVariable(
                "ambient_sensor_temperature", np.float64, ["response", "time"]
            )
            ambient_sensor_temperature_variable.units = "degrees C"
            ambient_sensor_temperature_variable.standard_name = "ambient_sensor_temperature"
            ambient_sensor_temperature_variable.long_name = "Ambient Sensor Temperature"

            # Create low presssure sensor pressure variable.
            low_pressure_sensor_pressure_variable = dataset.createVariable(
                "low_pressure_sensor_pressure", np.float64, ["response", "time"]
            )
            transfer_sensor_pressure_variable.units = "KPa"
            low_pressure_sensor_pressure_variable.standard_name = "low_pressure_sensor_pressure"
            low_pressure_sensor_pressure_variable.long_name = "Low Pressure Sensor Pressure"

            # Create low pressure sensor temperature variable.
            low_pressure_sensor_temperature_variable = dataset.createVariable(
                "low_pressure_sensor_temperature", np.float64, ["response", "time"]
            )
            low_pressure_sensor_temperature_variable.units = "degrees C"
            low_pressure_sensor_temperature_variable.standard_name = (
                "low_pressure_sensor_temperature"
            )
            low_pressure_sensor_temperature_variable.long_name = "Low Pressure Sensor Temperature"

            # Create response timestamp variable.
            response_timestamp_variable = dataset.createVariable(
                "response_timestamp", np.int64, ["response", "time"]
            )
            response_timestamp_variable.units = TIMESTAMP_UNITS
            response_timestamp_variable.standard_name = "response_timestamp"
            response_timestamp_variable.long_name = "Response Timestamp"

            # Add AZA response data.
            for j, collection in enumerate(collections):
                for i, response in enumerate(collection.responses):
                    transfer_sensor_pressure_variable[i, j] = response.transfer_sensor_pressure
                    transfer_sensor_temperature_variable[
                        i, j
                    ] = response.transfer_sensor_temperature
                    ambient_sensor_pressure_variable[i, j] = response.ambient_sensor_pressure
                    ambient_sensor_temperature_variable[i, j] = response.ambient_sensor_temperature
                    low_pressure_sensor_pressure_variable[
                        i, j
                    ] = response.low_pressure_sensor_pressure
                    low_pressure_sensor_temperature_variable[
                        i, j
                    ] = response.low_pressure_sensor_temperature
                    response_timestamp_variable[i, j] = nc.date2num(
                        response.source.timestamp, TIMESTAMP_UNITS
                    )

        return path

    def export_raw_log_message(self, message: Message) -> str:
        now = datetime.now(timezone.utc)
        date = now.date()

        directory = f"/data/raw/{date.year}/{date.month}"
        extension = ".host.txt" if message.address == self.host.connection.address else ".das.txt"
        path = f"{directory}/{date.isoformat()}{extension}"

        # Create any necessary directories.
        os.makedirs(directory, exist_ok=True)

        timestamp = now.isoformat()
        sender = "SERVER" if message.direction == MessageDirection.SEND else "DEVICE"
        content = message.content

        try:
            with open(path, "a") as stream:
                stream.write(f"{timestamp} {sender} {json.dumps(content)}\n")
        except Exception:
            self.log.error(f"Failed to write to raw log at [{path}]: {traceback.format_exc()}")

        return path

    async def __send_host(
        self,
        command_name: str,
        command: BytesLike,
        prefix: BytesLike,
        *,
        timeout: int = 20,
        retries: int = 2,
    ) -> tuple[Message, Message] | None:
        command = bytes_of(command)
        prefix = bytes_of(prefix)

        for retry in range(retries + 1):
            is_last_retry = retry >= retries

            connection = self.host.connection
            if not connection or not connection.connected:
                raise ConnectionError("Host connection is not active.")

            transport = Transport(connection)

            command_message = await transport.send(command)
            response_message = await transport.receive(prefix=prefix, timeout=timeout)

            if not response_message:
                if is_last_retry:
                    self.log.warning("Reporting no response...")
                    self.alert(
                        Level.ERROR,
                        f"host/no-response/{command_name}",
                        {
                            "command": command_message.content,
                            "timeout": timeout,
                            "retries": retries,
                        },
                    )
                    return None

                self.log.warning(f"Wait for response prefix '{prefix}' timed out. Retrying...")
                continue

            content = response_message.content.strip()

            if b"NO_REPLY" in content:
                if is_last_retry:
                    self.alert(
                        Level.ERROR,
                        f"host/no-remote-response/{command_name}",
                        {
                            "command": command_message.content,
                            "response": response_message.content,
                            "retries": retries,
                        },
                    )
                    return None

                self.log.warning("Received 'NO_REPLY' from remote unit. Retrying...")
                await asyncio.sleep(3)
                continue

            if b"NO_DATA" in content:
                if is_last_retry:
                    self.alert(
                        Level.ERROR,
                        f"host/no-remote-response-data/{command_name}",
                        {
                            "command": command_message.content,
                            "response": response_message.content,
                            "retries": retries,
                        },
                    )
                    return None

                self.log.warning("Received 'NO_DATA' from remote unit. Retrying...")
                await asyncio.sleep(3)
                continue

            if content.endswith(b"?") or b"NONE" in content:
                if is_last_retry:
                    self.alert(
                        Level.ERROR,
                        f"host/bad-response/{command_name}",
                        {
                            "command": command_message.content,
                            "response": response_message.content,
                            "retries": retries,
                        },
                    )
                    return None

                self.log.warning("Received bad response from remote unit. Retrying...")
                await asyncio.sleep(3)
                continue

            return command_message, response_message

        return None

    def __generate_sequence_number(self) -> int:
        while True:
            sequence_number = random.randint(1, 99)
            if sequence_number != self._last_sequence_number:
                self._last_sequence_number = sequence_number
                return sequence_number

    async def __send_das(
        self,
        command_name: str,
        command: bytes,
        prefix: bytes,
        *,
        timeout: int = 20,
        retries: int = 2,
    ) -> tuple[Message, Message] | None:
        command = bytes_of(command)
        prefix = bytes_of(prefix)

        for retry in range(retries + 1):
            is_last_retry = retry >= retries

            connection = self.das.connection
            if not connection:
                raise ConnectionError("DAS connection is not active.")

            transport = Transport(connection)

            sent = command.replace(b"?&", f"{self.__generate_sequence_number()}&".encode())
            command_message = await transport.send(sent)
            response_message = await transport.receive(prefix=prefix, timeout=timeout)

            if not response_message:
                if is_last_retry:
                    self.log.warning("Reporting no response...")
                    self.alert(
                        Level.ERROR,
                        f"das/no-response/{command_name}",
                        {
                            "command": sent,
                            "timeout": timeout,
                            "retries": retries,
                        },
                    )

                    return None

                self.log.warning(f"Wait for response prefix '{prefix}' timed out. Retrying...")
                continue

            response_info = DASMessageInfo.parse(response_message)
            error_flags = response_info.get_float_or_none(0)

            if error_flags != 0:
                if is_last_retry:
                    self.alert(
                        Level.ERROR,
                        f"das/bad-response/{command_name}",
                        {
                            "command": sent,
                            "response": command_message.content,
                            "error_flags": error_flags,
                        },
                    )

                    return None

                self.log.warning(
                    f"Received bad response with error flags [{error_flags}]. Retrying..."
                )
                await asyncio.sleep(3)
                continue

            return command_message, response_message

        return None


def _get_best_sens_responses(messages: Sequence[Message]) -> dict[int, HostSENSResponse]:
    mapping: dict[int, HostSENSResponse] = {}

    for message in messages:
        try:
            response = HostSENSResponse.parse(message)
        except ParseException:
            continue

        if response.source.address is None:
            continue

        previous = mapping.get(response.source.address)
        if not previous or response.error_count < previous.error_count:
            mapping[response.source.address] = response

    return mapping


def _get_best_si_responses(messages: Sequence[Message]) -> dict[int, HostSIResponse]:
    mapping: dict[int, HostSIResponse] = {}

    def count_valid_range_delays(response: HostSIResponse) -> int:
        count = 0

        for delay in response.range_delays.values():
            if delay > 0:
                count += 1

        return count

    for message in messages:
        try:
            response = HostSIResponse.parse(message)
        except ParseException:
            continue

        if response.source.address is None:
            continue

        previous = mapping.get(response.source.address)
        if not previous or count_valid_range_delays(response) > count_valid_range_delays(previous):
            mapping[response.source.address] = response

    return mapping


def stringify(dataset: Any) -> str:
    lines = []

    for variable in dataset.variables:
        lines.append(f"{variable} {dataset.variables[variable].shape()}")

    return "\n".join(lines)


TIMESTAMP_UNITS = "seconds since 1970-01-01"
