from pydantic import ByteSize

DEFAULT_BUFFER_READ_SIZE = ByteSize(1024)
"""Default chunk size used when reading bytes from a connection into a buffer."""

DEFAULT_BUFFER_SIZE = ByteSize(DEFAULT_BUFFER_READ_SIZE * 16)
"""Default maximum capacity of a connection buffer before older data is dropped."""

DEFAULT_BUFFER_DROP = DEFAULT_BUFFER_READ_SIZE
"""Default number of bytes to drop from the front of a full buffer when making room."""
