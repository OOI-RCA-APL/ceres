#!/bin/bash

IS_WINDOWS=$(uname | grep -i "windows")

set -e

function usage() {
    echo "Usage: ./host-rtsp.sh <video-file>? <stream-name>?"
}

# If `-h` is provided in any argument position, print usage and exit.
if [[ "$@" == *"-h"* ]]; then
    usage
    exit 0
fi

DIRECTORY=$(dirname "$0")

DOCKER=$(which docker)
FFMPEG=$(which ffmpeg)

if [ -z "$DOCKER" ]; then
    echo "`docker` command is not installed."
    exit 1
fi

if [ -z "$FFMPEG" ]; then
    echo "`ffmpeg` command is not installed."
    exit 1
fi

PORT=8554
DEFAULT_STREAM="stream"
DEFAULT_FILE="$DIRECTORY/host-rtsp-test-video.mp4"
CONTAINER_NAME="hosted-rtsp-server"

FILE="$1"
FILE="${FILE:-$DEFAULT_FILE}"

STREAM="$2"
STREAM="${STREAM:-$DEFAULT_STREAM}"


if [ -z "$FILE" ]; then
    echo "Video file not provided."
    exit 1
fi

echo "Stopping any running instance of the RTSP server."

set +e
"$DOCKER" stop "$CONTAINER_NAME"
set -e

echo "Done."

echo "Starting RTSP server."
# See https://github.com/bluenviron/mediamtx for details.
"$DOCKER" run --name hosted-rtsp-server --detach --rm -it \
                -e MTX_RTSPTRANSPORTS=tcp \
                -e MTX_WEBRTCADDITIONALHOSTS=192.168.x.x \
                -p 8554:8554 \
                -p 1935:1935 \
                -p 8888:8888 \
                -p 8889:8889 \
                -p 8890:8890/udp \
                -p 8189:8189/udp \
                bluenviron/mediamtx


URL="rtsp://localhost:8554/$STREAM"

echo "Streaming '$FILE' to '$URL'."

set +e
"$FFMPEG" -re -stream_loop -1 -i "$FILE" -c copy -f rtsp "$URL"
echo "Stopped streaming."

EXIT_CODE=$?

echo "Stopping RTSP server."
"$DOCKER" stop "$CONTAINER_NAME"

echo "Done."
exit $EXIT_CODE
