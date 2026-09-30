// The only code that touches FFmpeg's structs. Rust declares these functions by hand and sees
// every FFmpeg type as an opaque pointer, so no struct layout is mirrored on the Rust side.

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/dict.h>
#include <libavutil/error.h>
#include <libavutil/log.h>
#include <libavutil/mem.h>
#include <libavutil/pixdesc.h>

// A decoded format the H.264 encoder cannot take, which re-encoding does not convert.
#define CERES_ERROR_PIXEL_FORMAT FFERRTAG('C', 'P', 'I', 'X')

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

const AVCodecParameters *ceres_input_parameters(const AVFormatContext *input, int stream) {
    return input->streams[stream]->codecpar;
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

// Opens a muxer for `format` with one stream per `parameters` entry, timed in the parallel
// `nums/dens` time bases, writing through `write`. Each flush is one `write` call of at most
// `packet_size` bytes. Frees everything on failure.
int ceres_output_open(
    const char *format,
    const char *const *keys,
    const char *const *values,
    int count,
    const AVCodecParameters *const *parameters,
    const int *nums,
    const int *dens,
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
        AVStream *stream = avformat_new_stream(*output, NULL);
        if (stream == NULL) {
            error = AVERROR(ENOMEM);
            break;
        }
        error = avcodec_parameters_copy(stream->codecpar, parameters[index]);
        stream->codecpar->codec_tag = 0;
        // Safari plays HEVC only as `hvc1`, which requires the parameter sets out of band, so
        // the muxer default `hev1` stays only for a stream whose extradata lacks them.
        if (stream->codecpar->codec_id == AV_CODEC_ID_HEVC
            && stream->codecpar->extradata_size > 0) {
            stream->codecpar->codec_tag = MKTAG('h', 'v', 'c', '1');
        }
        stream->time_base = (AVRational){nums[index], dens[index]};
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

// Whether `parameters` carry the codec, size, and parameter sets output stream `stream` was
// opened with, so their packets can continue that stream's track.
int ceres_output_matches(
    const AVFormatContext *output,
    int stream,
    const AVCodecParameters *parameters
) {
    const AVCodecParameters *a = output->streams[stream]->codecpar;
    const AVCodecParameters *b = parameters;
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

// A decoder feeding the H.264 encoder. The encoder opens on the first decoded frame and lasts
// the whole session so its output stays one track, while each connection opens its own decoder.
typedef struct CeresTranscoder {
    AVCodecContext *decoder;
    AVCodecContext *encoder;
    AVCodecParameters *parameters;
    AVFrame *frame;
    AVRational time_base;
    AVRational frame_rate;
} CeresTranscoder;

void ceres_transcoder_close(CeresTranscoder **transcoder) {
    CeresTranscoder *t = *transcoder;
    if (t == NULL) {
        return;
    }
    avcodec_free_context(&t->decoder);
    avcodec_free_context(&t->encoder);
    avcodec_parameters_free(&t->parameters);
    av_frame_free(&t->frame);
    av_freep(transcoder);
}

// Opens a transcoder whose packets, in and out, are timed in `num/den`.
int ceres_transcoder_open(int num, int den, CeresTranscoder **transcoder) {
    CeresTranscoder *t = av_mallocz(sizeof *t);
    if (t == NULL) {
        return AVERROR(ENOMEM);
    }
    t->frame = av_frame_alloc();
    t->parameters = avcodec_parameters_alloc();
    if (t->frame == NULL || t->parameters == NULL) {
        ceres_transcoder_close(&t);
        return AVERROR(ENOMEM);
    }
    t->time_base = (AVRational){num, den};
    *transcoder = t;
    return 0;
}

// Opens a decoder for input stream `stream`, replacing the previous connection's.
int ceres_transcoder_connect(CeresTranscoder *t, AVFormatContext *input, int stream) {
    avcodec_free_context(&t->decoder);
    AVStream *source = input->streams[stream];
    const AVCodec *codec = avcodec_find_decoder(source->codecpar->codec_id);
    if (codec == NULL) {
        return AVERROR_DECODER_NOT_FOUND;
    }
    if ((t->decoder = avcodec_alloc_context3(codec)) == NULL) {
        return AVERROR(ENOMEM);
    }
    int error = avcodec_parameters_to_context(t->decoder, source->codecpar);
    if (error >= 0) {
        t->decoder->pkt_timebase = t->time_base;
        // Frame threads hold a frame per thread, a delay a live stream feels. Slices add none.
        t->decoder->flags |= AV_CODEC_FLAG_LOW_DELAY;
        t->decoder->thread_type = FF_THREAD_SLICE;
        t->decoder->thread_count = 0;
        error = avcodec_open2(t->decoder, codec, NULL);
    }
    if (error < 0) {
        avcodec_free_context(&t->decoder);
        return error;
    }
    if (t->encoder == NULL) {
        // RTP carries no frame rate, so a guess past any camera's means the estimate failed.
        AVRational rate = av_guess_frame_rate(input, source, NULL);
        t->frame_rate = rate.num > 0 && rate.den > 0 && av_q2d(rate) <= 120 ? rate
                                                                             : (AVRational){30, 1};
    }
    return 0;
}

// Sends a packet timed in the transcoder's time base to the decoder, leaving it blank.
int ceres_transcoder_send(CeresTranscoder *t, AVPacket *packet) {
    int error = avcodec_send_packet(t->decoder, packet);
    av_packet_unref(packet);
    // A live source loses packets, and one that fails to decode costs its frames, not the
    // session.
    return error == AVERROR_INVALIDDATA ? 0 : error;
}

static int open_encoder(CeresTranscoder *t, const AVFrame *frame) {
    if (frame->format != AV_PIX_FMT_YUV420P && frame->format != AV_PIX_FMT_YUVJ420P) {
        av_log(t->decoder, AV_LOG_ERROR, "cannot re-encode %s video\n",
               av_get_pix_fmt_name(frame->format));
        return CERES_ERROR_PIXEL_FORMAT;
    }
    const AVCodec *codec = avcodec_find_encoder_by_name("libopenh264");
    if (codec == NULL) {
        return AVERROR_ENCODER_NOT_FOUND;
    }
    AVCodecContext *encoder = avcodec_alloc_context3(codec);
    if (encoder == NULL) {
        return AVERROR(ENOMEM);
    }
    double rate = av_q2d(t->frame_rate);
    encoder->width = frame->width;
    encoder->height = frame->height;
    encoder->pix_fmt = frame->format;
    encoder->sample_aspect_ratio = frame->sample_aspect_ratio;
    encoder->time_base = t->time_base;
    encoder->framerate = t->frame_rate;
    // The encoder's 200 kb/s default blurs anything larger than a thumbnail, so the rate
    // scales with the picture, 0.1 bits per pixel.
    encoder->bit_rate = (int64_t)(0.1 * frame->width * frame->height * rate);
    // Two seconds between keyframes. The default twelve frames spends the rate on intra frames.
    encoder->gop_size = (int)(2 * rate + 0.5);
    encoder->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
    encoder->thread_count = 0;
    int error = avcodec_open2(encoder, codec, NULL);
    if (error >= 0) {
        error = avcodec_parameters_from_context(t->parameters, encoder);
    }
    if (error < 0) {
        avcodec_free_context(&encoder);
        return error;
    }
    t->encoder = encoder;
    return 0;
}

static int encode_frame(CeresTranscoder *t) {
    AVFrame *frame = t->frame;
    frame->pts = frame->best_effort_timestamp;
    if (frame->pts == AV_NOPTS_VALUE) {
        return 0;
    }
    int error = 0;
    if (t->encoder == NULL) {
        error = open_encoder(t, frame);
    } else if (frame->width != t->encoder->width || frame->height != t->encoder->height ||
               frame->format != t->encoder->pix_fmt) {
        error = AVERROR_INPUT_CHANGED;
    }
    if (error < 0) {
        return error;
    }
    frame->pict_type = AV_PICTURE_TYPE_NONE;
    return avcodec_send_frame(t->encoder, frame);
}

// Returns 1 with an encoded packet timed in the transcoder's time base, 0 when the decoder
// needs another packet, and a negative error otherwise. `AVERROR_INPUT_CHANGED` means a frame's
// size or format differs from the encoder's, which lasts the session.
int ceres_transcoder_receive(CeresTranscoder *t, AVPacket *packet) {
    for (;;) {
        if (t->encoder != NULL) {
            int error = avcodec_receive_packet(t->encoder, packet);
            if (error != AVERROR(EAGAIN)) {
                return error < 0 ? error : 1;
            }
        }
        int error = avcodec_receive_frame(t->decoder, t->frame);
        if (error == AVERROR(EAGAIN)) {
            return 0;
        }
        if (error == AVERROR_INVALIDDATA) {
            continue;
        }
        if (error < 0) {
            return error;
        }
        error = encode_frame(t);
        av_frame_unref(t->frame);
        if (error < 0) {
            return error;
        }
    }
}

// The encoder's stream parameters, null until a received frame has opened the encoder.
const AVCodecParameters *ceres_transcoder_parameters(const CeresTranscoder *t) {
    return t->encoder != NULL ? t->parameters : NULL;
}

void ceres_error_describe(int error, char *buffer, size_t size) {
    if (error == CERES_ERROR_PIXEL_FORMAT) {
        snprintf(buffer, size, "re-encoding supports only 8-bit 4:2:0 video");
        return;
    }
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
