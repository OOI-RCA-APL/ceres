// The only code that touches FFmpeg's structs. Rust declares these functions by hand and sees
// every FFmpeg type as an opaque pointer, so no struct layout is mirrored on the Rust side.

#include <libavformat/avformat.h>
#include <libavutil/dict.h>
#include <libavutil/error.h>
#include <libavutil/mem.h>

// Builds a dictionary from `count` parallel keys and values.
static int build_options(
    const char *const *keys, const char *const *values, int count, AVDictionary **dictionary
) {
    for (int index = 0; index < count; index++) {
        int error = av_dict_set(dictionary, keys[index], values[index], 0);
        if (error < 0) {
            return error;
        }
    }
    return 0;
}

// Fails with `AVERROR_OPTION_NOT_FOUND` when FFmpeg left an option unused, so a misspelled key
// is an error instead of a silent default.
static int check_consumed(AVDictionary **dictionary, int error) {
    if (error >= 0 && av_dict_count(*dictionary) > 0) {
        error = AVERROR_OPTION_NOT_FOUND;
    }
    av_dict_free(dictionary);
    return error;
}

int ceres_input_open(
    const char *url,
    const char *const *keys,
    const char *const *values,
    int count,
    int (*interrupt)(void *),
    void *opaque,
    AVFormatContext **input
) {
    AVDictionary *dictionary = NULL;
    int error = build_options(keys, values, count, &dictionary);
    if (error >= 0 && (*input = avformat_alloc_context()) == NULL) {
        error = AVERROR(ENOMEM);
    }
    if (error < 0) {
        av_dict_free(&dictionary);
        return error;
    }
    (*input)->interrupt_callback.callback = interrupt;
    (*input)->interrupt_callback.opaque = opaque;
    // Frees the context itself on failure.
    error = check_consumed(&dictionary, avformat_open_input(input, url, NULL, &dictionary));
    if (error >= 0) {
        error = avformat_find_stream_info(*input, NULL);
    }
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

int ceres_input_video_stream(AVFormatContext *input) {
    return av_find_best_stream(input, AVMEDIA_TYPE_VIDEO, -1, -1, NULL, 0);
}

void ceres_input_time_base(const AVFormatContext *input, int stream, int *num, int *den) {
    AVRational time_base = input->streams[stream]->time_base;
    *num = time_base.num;
    *den = time_base.den;
}

AVPacket *ceres_packet_alloc(void) { return av_packet_alloc(); }

void ceres_packet_free(AVPacket **packet) { av_packet_free(packet); }

void ceres_packet_unref(AVPacket *packet) { av_packet_unref(packet); }

int ceres_packet_stream(const AVPacket *packet) { return packet->stream_index; }

// Reads the packet's timing in its stream's time base, `AV_NOPTS_VALUE` where unset.
void ceres_packet_timing(const AVPacket *packet, int64_t *pts, int64_t *dts, int64_t *duration) {
    *pts = packet->pts;
    *dts = packet->dts;
    *duration = packet->duration;
}

void ceres_packet_set_timing(AVPacket *packet, int64_t pts, int64_t dts) {
    packet->pts = pts;
    packet->dts = dts;
}

int ceres_packet_is_key(const AVPacket *packet) { return (packet->flags & AV_PKT_FLAG_KEY) != 0; }

// Frees a muxer whose header may or may not be written, along with its custom I/O context.
static void free_output(AVFormatContext **output) {
    if ((*output)->pb != NULL) {
        av_freep(&(*output)->pb->buffer);
        avio_context_free(&(*output)->pb);
    }
    avformat_free_context(*output);
    *output = NULL;
}

// Opens a muxer for `format` whose streams copy the input's `streams`, writing through `write`.
// Each flush is one `write` call of at most `packet_size` bytes. Frees everything on failure.
int ceres_output_open(
    const char *format,
    const char *const *keys,
    const char *const *values,
    int count,
    const AVFormatContext *input,
    const int *streams,
    int stream_count,
    int packet_size,
    int (*write)(void *, const uint8_t *, int),
    void *opaque,
    AVFormatContext **output
) {
    AVDictionary *dictionary = NULL;
    int error = build_options(keys, values, count, &dictionary);
    if (error >= 0) {
        error = avformat_alloc_output_context2(output, NULL, format, NULL);
    }
    for (int index = 0; error >= 0 && index < stream_count; index++) {
        const AVStream *source = input->streams[streams[index]];
        AVStream *stream = avformat_new_stream(*output, NULL);
        if (stream == NULL) {
            error = AVERROR(ENOMEM);
            break;
        }
        error = avcodec_parameters_copy(stream->codecpar, source->codecpar);
        stream->codecpar->codec_tag = 0;
        stream->time_base = source->time_base;
    }
    if (error >= 0) {
        // One byte of slack keeps a full packet from flushing before its own explicit flush.
        unsigned char *buffer = av_malloc(packet_size + 1);
        AVIOContext *io =
            buffer ? avio_alloc_context(buffer, packet_size + 1, 1, opaque, NULL, write, NULL)
                   : NULL;
        if (io == NULL) {
            av_free(buffer);
            error = AVERROR(ENOMEM);
        } else {
            io->max_packet_size = packet_size;
            (*output)->pb = io;
            (*output)->flags |= AVFMT_FLAG_CUSTOM_IO;
            error = check_consumed(&dictionary, avformat_write_header(*output, &dictionary));
        }
    }
    av_dict_free(&dictionary);
    if (error < 0 && *output != NULL) {
        free_output(output);
    }
    return error;
}

// Writes a packet timed in `num/den` to output stream `stream`, rescaling it to the stream's
// time base. The muxer takes the packet's data and leaves it blank.
int ceres_output_write(AVFormatContext *output, int stream, AVPacket *packet, int num, int den) {
    packet->stream_index = stream;
    av_packet_rescale_ts(packet, (AVRational){num, den}, output->streams[stream]->time_base);
    return av_interleaved_write_frame(output, packet);
}

// Writes the trailer unless `abandon` is set, then frees the muxer and its I/O context.
int ceres_output_close(AVFormatContext **output, int abandon) {
    int error = 0;
    if (!abandon) {
        error = av_write_trailer(*output);
        avio_flush((*output)->pb);
    }
    free_output(output);
    return error;
}

int ceres_output_sdp(AVFormatContext *output, char *buffer, int size) {
    return av_sdp_create(&output, 1, buffer, size);
}

void ceres_error_describe(int error, char *buffer, size_t size) {
    av_strerror(error, buffer, size);
}
