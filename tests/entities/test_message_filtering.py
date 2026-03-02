from ceres import Message
from tests import testing


async def test_message_id_filtering():
    await testing.execute_id_filter_test(Message)


async def test_message_connection_filtering():
    await testing.execute_string_filter_test(Message, "connection")


async def test_message_address_filtering():
    await testing.execute_address_filter_test(Message)


async def test_message_timestamp_filtering():
    await testing.execute_timestamp_filter_test(Message)


async def test_message_direction_filtering():
    await testing.execute_enum_filter_test(Message, "direction", Message.Direction)


async def test_message_content_filtering():
    await testing.execute_string_filter_test(Message, "content", prefixed=False)
