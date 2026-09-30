// The only code that touches FFmpeg's structs. Rust declares these functions by hand and sees
// every FFmpeg type as an opaque pointer, so no struct layout is mirrored on the Rust side.

#include <stdarg.h>
#include <string.h>

#include <libavformat/avformat.h>
#include <libavutil/dict.h>
#include <libavutil/error.h>
#include <libavutil/log.h>
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

void ceres_packet_set_timing(AVPacket *packet, int64_t pts, int64_t dts, int64_t duration) {
    packet->pts = pts;
    packet->dts = dts;
    packet->duration = duration;
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
        // Safari plays HEVC only as `hvc1`, which requires the parameter sets out of band, so
        // the muxer default `hev1` stays only for a stream whose extradata lacks them.
        if (stream->codecpar->codec_id == AV_CODEC_ID_HEVC
            && stream->codecpar->extradata_size > 0) {
            stream->codecpar->codec_tag = MKTAG('h', 'v', 'c', '1');
        }
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
            // The header is the MP4 init segment, which a player needs before any fragment.
            avio_flush(io);
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

// The time base the muxer chose for output stream `stream`, fixed once the header is written.
void ceres_output_time_base(const AVFormatContext *output, int stream, int *num, int *den) {
    AVRational time_base = output->streams[stream]->time_base;
    *num = time_base.num;
    *den = time_base.den;
}

// Whether input stream `source` carries the codec, size, and parameter sets output stream
// `stream` was opened with, so its packets can continue that stream's track.
int ceres_output_matches(
    const AVFormatContext *output,
    int stream,
    const AVFormatContext *input,
    int source
) {
    const AVCodecParameters *a = output->streams[stream]->codecpar;
    const AVCodecParameters *b = input->streams[source]->codecpar;
    return a->codec_id == b->codec_id && a->width == b->width && a->height == b->height &&
           a->extradata_size == b->extradata_size &&
           (a->extradata_size == 0 || memcmp(a->extradata, b->extradata, a->extradata_size) == 0);
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

static void (*log_sink)(int level, const char *line);

// Formats one message and hands it to the sink. Verbose levels are dropped before
// formatting because the demuxer logs them per packet.
static void route_log(void *context, int level, const char *format, va_list arguments) {
    if (level > AV_LOG_INFO) {
        return;
    }
    char line[1024];
    int print_prefix = 1;
    av_log_format_line2(context, level, format, arguments, line, sizeof line, &print_prefix);
    size_t length = strlen(line);
    while (length > 0 && (line[length - 1] == '\n' || line[length - 1] == '\r')) {
        line[--length] = '\0';
    }
    if (length > 0) {
        log_sink(level, line);
    }
}

void ceres_log_route(void (*sink)(int level, const char *line)) {
    log_sink = sink;
    av_log_set_callback(route_log);
}
