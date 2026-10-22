from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

import h5netcdf
import numpy
import pytest

from ceres import Particle, ParticleData, Unit
from ceres.__internal__.netcdf import NetCDFRows, NetCDFVariable, netcdf_variables
from ceres.address import Address
from ceres.data import Float32, Int16, PackedSequence, UInt16
from ceres.entity import EntityType
from ceres.event import LogEvent
from ceres.exporter import ExportRunState, ExportSchema, NetCDFFormat
from tests.test_exporter import RECENT, START, Exported, Live, refusal
from tests.testing import wait_for_condition

if TYPE_CHECKING:
    from pathlib import Path


class DepthData(ParticleData):
    meters: float


class FlowData(ParticleData):
    rate: Annotated[float, Unit("m3 s-1")]
    flow_speed: float
    depth: DepthData | None = None


class ProbeData(ParticleData):
    gain: float
    trace: Annotated[list[float], Unit("V")]


class SweepData(ParticleData):
    gain: float
    levels: Sequence[float]


class GaugeData(ParticleData):
    celsius: Annotated[float, Unit("degC")]
    count: UInt16 = 0
    ok: bool = True
    label: str = ""
    sampled: datetime | None = None
    vector: tuple[float, float, float] = (0, 0, 0)
    grid: tuple[tuple[Int16, Int16], tuple[Int16, Int16]] = ((0, 0), (0, 0))
    window: Annotated[tuple[Float32, ...], PackedSequence(length=2)] = (0, 0)
    ragged: list[float] | None = None
    flow: FlowData | None = None
    probe: ProbeData | None = None
    sweep: SweepData | None = None
    spectrum: tuple[float, ...] | None = None


class Gauge(Particle[GaugeData]):
    type = "gauge"
    data: GaugeData


class CollidingData(ParticleData):
    flow_speed: float
    flow: FlowData


class Colliding(Particle[CollidingData]):
    type = "colliding"
    data: CollidingData


SCHEMA = ExportSchema.create(EntityType.PARTICLE, Gauge)


def gauge(
    minutes: float, celsius: float = 1.5, id: int = 1, at: datetime = START, **data: Any
) -> Gauge:
    return Gauge(
        type="gauge",
        id=UUID(int=id),
        address=Address("@archive"),
        connection=data.pop("connection", "serial"),
        timestamp=at + timedelta(minutes=minutes),
        data=GaugeData(celsius=celsius, **data),
    )


def netcdf(**exporter: Any) -> dict[str, Any]:
    return {
        "exports": "particle",
        "type": f"{__name__}.Gauge",
        "format": "netcdf",
        "live": False,
        **exporter,
    }


def read(path: Path) -> dict[str, Any]:
    with h5netcdf.File(path, "r") as file:
        return {
            "attributes": dict(file.attrs),
            "variables": {name: variable[:] for name, variable in file.variables.items()},
            "variable_attributes": {
                name: dict(variable.attrs) for name, variable in file.variables.items()
            },
            "dimensions": {name: variable.dimensions for name, variable in file.variables.items()},
        }


def test_variables_follow_the_data_class() -> None:
    variables, omitted = netcdf_variables(SCHEMA.fields)

    assert [(variable.name, variable.dtype, variable.shape) for variable in variables] == [
        ("celsius", "f8", ()),
        ("count", "u2", ()),
        ("ok", "i1", ()),
        ("label", "str", ()),
        ("sampled", "f8", ()),
        ("vector", "f8", (3,)),
        ("grid", "i2", (2, 2)),
        ("window", "f4", (2,)),
        ("flow_rate", "f8", ()),
        ("flow_speed", "f8", ()),
        ("flow_depth_meters", "f8", ()),
    ]
    units = {variable.name: variable.units for variable in variables if variable.units}
    assert units == {"celsius": "degC", "flow_rate": "m3 s-1"}
    assert omitted == ("ragged", "probe", "sweep", "spectrum")
    assert NetCDFVariable("grid", "i2", ("grid",), (2, 2)).dimensions == (
        "time",
        "grid_0",
        "grid_1",
    )


def test_a_wide_row_allocates_chunks_of_fewer_rows() -> None:
    narrow = NetCDFVariable("narrow", "f8", ("narrow",))
    wide = NetCDFVariable("wide", "f8", ("wide",), (1_000_000,))

    assert NetCDFRows([narrow]).chunk_rows == 65536
    assert NetCDFRows([wide]).chunk_rows == 1


def test_an_exporter_warns_of_the_fields_its_files_leave_out(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, **netcdf())
    system = exported.component.system

    with system.events.every(LogEvent).read() as reader:
        system.exporters.add(exported.exporter)
        logged: list[Any] = reader.clear()

    warning = "leaves out the fields its format cannot store: 'ragged', 'probe', 'sweep'"
    assert any(warning in event.entry.content for event in logged)


async def test_a_run_writes_a_variable_per_field(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, **netcdf())
    sampled = datetime(2026, 1, 1, 0, 5, 30, 250000, tzinfo=UTC)
    await exported.store(
        gauge(10, 2.5, id=2, sampled=sampled, flow=FlowData(rate=3, flow_speed=4)),
        gauge(5, id=1, connection=None, vector=(1, 2, 3), grid=((1, 2), (3, 4)), label="abc"),
    )

    await exported.run()

    file = read(tmp_path / "2026/01/01/00.nc")
    variables = file["variables"]
    assert file["attributes"] == {
        "exporter": "messages",
        "address": "@archive",
        "particle_type": "gauge",
    }
    assert variables["time"].tolist() == [
        (START + timedelta(minutes=5)).timestamp(),
        (START + timedelta(minutes=10)).timestamp(),
    ]
    assert [bytes(row).decode() for row in variables["id"]] == [str(UUID(int=1)), str(UUID(int=2))]
    assert variables["connection"].tolist() == [-1, 0]
    assert variables["connection_name"].tolist() == [b"serial"]
    assert variables["celsius"].tolist() == [1.5, 2.5]
    assert variables["sampled"][1] == sampled.timestamp()
    assert variables["label"].tolist() == [b"abc", b""]
    assert variables["vector"].tolist() == [[1, 2, 3], [0, 0, 0]]
    assert variables["grid"].tolist()[0] == [[1, 2], [3, 4]]
    assert variables["flow_rate"].tolist() == [pytest.approx(9.969209968386869e36), 3]
    attributes = file["variable_attributes"]
    assert attributes["celsius"] == {
        "_FillValue": attributes["celsius"]["_FillValue"],
        "units": "degC",
    }
    assert attributes["sampled"]["units"] == attributes["time"]["units"]
    assert file["dimensions"]["id"] == ("time", "string36")


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 1, 1, 0, 0, 0, 999999, tzinfo=UTC),
        # Its seconds times 1e6 lands just below the whole microsecond, so truncating reads it wrong.
        datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=2216497697421117),
        datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=2**32 * 10**6 - 1),
    ],
    ids=["microsecond", "rounding", "2106"],
)
async def test_keys_survive_the_seconds_time_variable(tmp_path: Path, moment: datetime) -> None:
    exported = Exported.create(tmp_path, **netcdf(period="all", path="all"))
    await exported.store(gauge(0, at=moment))
    await exported.run(after=moment, hours=1)

    keys = [key async for key in NetCDFFormat().keys(tmp_path / "all.nc", SCHEMA)]

    assert keys == [(moment, UUID(int=1))]


async def test_reruns_write_equal_bytes(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, **netcdf())
    await exported.store(gauge(5, id=3), gauge(5, id=2), gauge(70, id=1, connection="usb"))

    await exported.run()
    first = exported.files()
    await exported.run()

    assert exported.files() == first
    assert list(first) == ["2026/01/01/00.nc", "2026/01/01/01.nc"]


async def test_merge_keeps_records_the_database_lost_and_lets_it_win(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path / "merged", **netcdf())
    lost = gauge(10, id=1, connection="usb")
    await exported.store(lost, gauge(20, id=2))
    await exported.run()

    await exported.component.system.particles.where(id=lost.id).delete()
    await exported.component.system.particles.where(id=UUID(int=2)).delete()
    await exported.store(gauge(5, id=3), gauge(20, 9.5, id=2))
    await exported.run()

    whole = Exported.create(tmp_path / "whole", **netcdf())
    await whole.component.system.particles.where().delete()
    await whole.store(lost, gauge(5, id=3), gauge(20, 9.5, id=2))
    await whole.run()
    assert exported.files() == whole.files()
    variables = read(tmp_path / "merged/2026/01/01/00.nc")["variables"]
    assert variables["celsius"].tolist() == [1.5, 1.5, 9.5]
    assert variables["connection_name"].tolist() == [b"serial", b"usb"]


async def test_merge_refuses_a_file_with_other_variables(tmp_path: Path) -> None:
    exported = Exported.create(tmp_path, **netcdf())
    await exported.store(gauge(10))
    (tmp_path / "2026/01/01").mkdir(parents=True)
    with h5netcdf.File(tmp_path / "2026/01/01/00.nc", "w") as file:
        file.dimensions = {"time": 1}
        file.create_variable("other", ("time",), "f8")[:] = numpy.array([1.0])

    run = await exported.run()

    assert run.state == ExportRunState.FAILED
    assert run.exception is not None and "has other variables" in run.exception


async def test_live_export_equals_a_rerun(tmp_path: Path) -> None:
    live = await Live.started(tmp_path / "live", **netcdf(live=True))
    await live.write(gauge(10, id=1, at=RECENT), gauge(30, id=3, at=RECENT))
    path = tmp_path / f"live/{RECENT:%Y/%m/%d/%H}.nc"
    await wait_for_rows(path, 2)
    await live.write(gauge(20, id=2, at=RECENT), gauge(70, id=5, at=RECENT))
    await live.write(gauge(40, id=4, at=RECENT))
    await wait_for_rows(path, 4)

    rerun = Exported.create(tmp_path / "rerun", **netcdf())
    await rerun.component.system.particles.where().delete()
    await rerun.store(*[gauge(m, id=i, at=RECENT) for i, m in enumerate((10, 20, 30, 40, 70), 1)])
    await rerun.run(after=RECENT)

    await wait_for_condition("both files match", lambda: live.files() == rerun.files(), 30)
    await live.component.system.stop()


async def test_a_live_tick_never_reads_the_file_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: Any) -> Any:
        raise AssertionError("a whole-file format read its keys on a live tick")

    live = await Live.started(tmp_path, **netcdf(live=True))
    monkeypatch.setattr(NetCDFFormat, "keys", refuse)
    path = tmp_path / f"{RECENT:%Y/%m/%d/%H}.nc"

    await live.write(gauge(10, id=1, at=RECENT))
    await wait_for_rows(path, 1)
    await live.write(gauge(20, id=2, at=RECENT))

    await wait_for_rows(path, 2)
    await live.component.system.stop()


async def test_the_class_form_passes_netcdf_attributes(tmp_path: Path) -> None:
    arguments = {"attributes": {"celsius": {"long_name": "abc"}}, "global_attributes": {"a": "b"}}
    exported = Exported.create(
        tmp_path, **netcdf(format={"class": "netcdf", "arguments": arguments})
    )
    await exported.store(gauge(10))

    await exported.run()

    file = read(tmp_path / "2026/01/01/00.nc")
    assert file["attributes"]["a"] == "b"
    assert file["variable_attributes"]["celsius"]["long_name"] == "abc"
    assert exported.exporter.format_name == "netcdf"


def test_config_refuses_netcdf_for_other_kinds_and_untyped_particles() -> None:
    assert "cannot export message records" in refusal(format="netcdf")
    assert "needs a particle `type`" in refusal(**{**netcdf(), "type": None})
    assert "needs a period shorter than `all`" in refusal(
        **netcdf(live=True, period="all", path="all")
    )


def test_config_refuses_netcdf_variables_whose_names_collide() -> None:
    assert "netcdf variable 'flow_speed' collides" in refusal(
        **netcdf(type=f"{__name__}.Colliding")
    )


async def wait_for_rows(path: Path, count: int) -> None:
    def written() -> bool:
        try:
            with h5netcdf.File(path, "r") as file:
                return file.dimensions["time"].size == count
        except OSError:
            return False

    await wait_for_condition(f"{path.name} holds {count} rows", written, 30)
