from datetime import datetime, timedelta

import pytest

from ceres.connection import Buffer, Chunk, SplitByLine, Splitter


def test_buffer_general():
    start = datetime(2000, 1, 1)
    buffer = Buffer()
    assert not bool(buffer)
    buffer.push(b"abc", start)
    buffer.push(b"def", start + timedelta(seconds=1))
    buffer.push(b"ghi", timedelta(seconds=1))
    assert buffer == Buffer(
        [
            (b"abc", start),
            (b"def", start + timedelta(seconds=1)),
            (b"ghi", start + timedelta(seconds=2)),
        ]
    )
    assert bool(buffer)

    assert buffer.pop(2) == Chunk(b"ab", start)
    assert buffer.data == b"cdefghi"
    assert buffer.size == len(b"cdefghi")
    assert bool(buffer)
    assert len(buffer) == buffer.size
    assert buffer == Buffer(
        [
            (b"c", start),
            (b"def", start + timedelta(seconds=1)),
            (b"ghi", start + timedelta(seconds=2)),
        ]
    )

    assert buffer.pop(1) == Chunk(b"c", start)
    assert buffer.data == b"defghi"
    assert buffer.pop(3) == Chunk(b"def", start + timedelta(seconds=1))
    assert buffer.data == b"ghi"
    assert buffer.size == len(b"ghi")

    buffer.pop(1)
    assert buffer == Buffer([(b"hi", start + timedelta(seconds=2))])
    chunk = buffer.pop(20)
    assert buffer.data == b""
    assert buffer.size == 0
    assert not bool(buffer)
    assert chunk == Chunk(b"hi", start + timedelta(seconds=2))

    assert buffer._data == b""
    assert buffer._entries == []
    assert buffer._start_position == 0
    assert not list(buffer.chunks)

    buffer.push(b"jkl", start)
    buffer.clear()
    assert not buffer
    assert not list(buffer.chunks)


@pytest.mark.parametrize(
    "splitter,data,chunks,remainder",
    [
        [
            None,
            [
                (b"abc", datetime(2000, 1, 1)),
                (b"def", datetime(2000, 1, 1) + timedelta(seconds=1)),
                (b"ghi", datetime(2000, 1, 1) + timedelta(seconds=2)),
            ],
            [
                (b"abc", datetime(2000, 1, 1)),
                (b"def", datetime(2000, 1, 1) + timedelta(seconds=1)),
                (b"ghi", datetime(2000, 1, 1) + timedelta(seconds=2)),
            ],
            b"",
        ],
        [
            SplitByLine(),
            [
                (b"abc\n", datetime(2000, 1, 1)),
                (b"de\n\nf", datetime(2000, 1, 1) + timedelta(seconds=1)),
                (b"gh\r\ni\njkl", datetime(2000, 1, 1) + timedelta(seconds=2)),
            ],
            [
                (b"abc\n", datetime(2000, 1, 1)),
                (b"de\n", datetime(2000, 1, 1) + timedelta(seconds=1)),
                (b"\n", datetime(2000, 1, 1) + timedelta(seconds=1)),
                (b"fgh\r\n", datetime(2000, 1, 1) + timedelta(seconds=2)),
                (b"i\n", datetime(2000, 1, 1) + timedelta(seconds=2)),
            ],
            b"jkl",
        ],
    ],
)
def test_connection_buffer_split_drain(
    splitter: Splitter | None,
    data: list[tuple[bytes, datetime]] | None,
    chunks: list[tuple[bytes, datetime]],
    remainder: bytes,
):
    buffer = Buffer(data)
    expected = [Chunk(data, timestamp) for data, timestamp in chunks]
    splits = [chunk.resolve() for chunk in buffer.split(splitter)]
    assert splits == expected
    drained = list(buffer.drain(splitter))
    assert drained == expected
    assert buffer.data == remainder


def test_pop_to_size():
    start = datetime(2000, 1, 1)
    buffer = Buffer(
        [
            (b"abc", start),
            (b"defghij", start + timedelta(seconds=1)),
        ]
    )
    popped = buffer.pop_to_size(5)
    assert popped == Chunk(b"abcde", start + timedelta(seconds=1))
    assert buffer.data == b"fghij"
    popped = buffer.pop_to_size(10)
    assert popped is None

    buffer = Buffer(
        [
            (b"abcde", start),
            (b"fghij", start + timedelta(seconds=1)),
            (b"klmno", start + timedelta(seconds=2)),
        ]
    )

    popped = buffer.pop_to_size(5, by=3)
    assert popped == Chunk(b"abcdefghijkl", start + timedelta(seconds=2))
    assert buffer.data == b"mno"
