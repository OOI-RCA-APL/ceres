#!/bin/bash

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

FILE="${1:-$DIRECTORY/host-rtsp-test-video.mp4}"
STREAM="${2:-stream}"

# The test server loops the file until stopped. `--help` after `--` lists the fault flags
# for testing reconnects.
exec cargo run --quiet --manifest-path "$DIRECTORY/../rust/Cargo.toml" -p ceres-rtsp-server -- \
    --host 0.0.0.0 --port 8554 --path "$STREAM" --clip "$FILE"
