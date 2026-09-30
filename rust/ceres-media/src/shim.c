// The only code that touches FFmpeg's structs. Rust declares these functions by hand and sees
// every FFmpeg type as an opaque pointer, so no struct layout is mirrored on the Rust side.

#include <libavformat/avformat.h>
#include <libavutil/error.h>

int ceres_input_open(const char *url, AVFormatContext **input) {
    int error = avformat_open_input(input, url, NULL, NULL);
    if (error < 0) {
        return error;
    }
    error = avformat_find_stream_info(*input, NULL);
    if (error < 0) {
        avformat_close_input(input);
    }
    return error;
}

void ceres_input_close(AVFormatContext **input) { avformat_close_input(input); }

// Returns 1 with a packet read, 0 at the end of the input, and a negative error otherwise.
int ceres_input_read(AVFormatContext *input, AVPacket *packet) {
    int error = av_read_frame(input, packet);
    if (error == AVERROR_EOF) {
        return 0;
    }
    return error < 0 ? error : 1;
}

AVPacket *ceres_packet_alloc(void) { return av_packet_alloc(); }

void ceres_packet_free(AVPacket **packet) { av_packet_free(packet); }

void ceres_packet_unref(AVPacket *packet) { av_packet_unref(packet); }

int ceres_packet_stream(const AVPacket *packet) { return packet->stream_index; }

void ceres_error_describe(int error, char *buffer, size_t size) {
    av_strerror(error, buffer, size);
}
