from ceres import Particle
from tests import testing


async def test_particle_id_filtering():
    await testing.execute_id_filter_test(Particle)


async def test_particle_address_filtering():
    await testing.execute_address_filter_test(Particle)


async def test_particle_timestamp_filtering():
    await testing.execute_timestamp_filter_test(Particle)


async def test_particle_type_filtering():
    await testing.execute_string_filter_test(Particle, "type")


async def test_particle_data_filtering():
    await testing.execute_json_data_filter_test(Particle, "data")
