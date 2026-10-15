//! H.264 and H.265 access units in the Annex B form str0m's packetizers read.

use std::borrow::Cow;

use ceres_media::MediaCodec;

/// Returns a keyframe with the track's parameter sets in front when it carries none of its
/// own, since a browser joining at that keyframe cannot decode it without them.
///
/// `extradata` is used only in Annex B form, the form an RTSP source and the H.264 encoder
/// both give.
pub(crate) fn with_parameter_sets<'a>(
    data: &'a [u8],
    extradata: &[u8],
    codec: MediaCodec,
    key: bool,
) -> Cow<'a, [u8]> {
    let carries_them = NalUnits(data).any(|unit| {
        unit.first()
            .is_some_and(|header| is_sequence_parameter_set(codec, *header))
    });
    let annex_b = extradata.starts_with(&[0, 0, 1]) || extradata.starts_with(&[0, 0, 0, 1]);
    if !key || carries_them || !annex_b {
        return Cow::Borrowed(data);
    }

    Cow::Owned([extradata, data].concat())
}

/// Whether a NAL unit whose first byte is `header` is a sequence parameter set.
///
/// H.264 keeps the unit type in the low five bits, type 7, and H.265 in the six bits after
/// the first, type 33.
fn is_sequence_parameter_set(codec: MediaCodec, header: u8) -> bool {
    match codec {
        MediaCodec::H264 => header & 0x1f == 7,
        MediaCodec::H265 => (header >> 1) & 0x3f == 33,
        MediaCodec::Other => false,
    }
}

/// The NAL units of an Annex B access unit, without their start codes.
struct NalUnits<'a>(&'a [u8]);

impl<'a> Iterator for NalUnits<'a> {
    type Item = &'a [u8];

    fn next(&mut self) -> Option<&'a [u8]> {
        loop {
            let rest = &self.0[start_code(self.0)? + 3..];
            let end = start_code(rest).unwrap_or(rest.len());
            self.0 = &rest[end..];
            // A four-byte start code leaves its leading zero on the unit before it.
            let length = rest[..end]
                .iter()
                .rposition(|byte| *byte != 0)
                .map_or(0, |last| last + 1);
            if length > 0 {
                return Some(&rest[..length]);
            }
        }
    }
}

fn start_code(data: &[u8]) -> Option<usize> {
    data.windows(3).position(|window| window == [0, 0, 1])
}

#[cfg(test)]
mod tests {
    use super::*;

    const SPS: [u8; 3] = [0x67, 1, 2];
    const PPS: [u8; 2] = [0x68, 3];
    const IDR: [u8; 3] = [0x65, 4, 5];

    // H.265 headers are two bytes, the type shifted left one.
    const HEVC_VPS: [u8; 3] = [32 << 1, 1, 1];
    const HEVC_SPS: [u8; 3] = [33 << 1, 1, 2];
    const HEVC_PPS: [u8; 3] = [34 << 1, 1, 3];
    const HEVC_IDR: [u8; 3] = [19 << 1, 1, 4];

    fn annex_b(units: &[&[u8]]) -> Vec<u8> {
        units
            .iter()
            .flat_map(|unit| [&[0, 0, 0, 1][..], unit].concat())
            .collect()
    }

    #[test]
    fn splits_units_at_either_start_code() {
        let data = [
            &[0, 0, 0, 1][..],
            &SPS,
            &[0, 0, 1],
            &PPS,
            &[0, 0, 0, 1],
            &IDR,
        ]
        .concat();
        let units: Vec<&[u8]> = NalUnits(&data).collect();
        assert_eq!(units, [&SPS[..], &PPS, &IDR]);
    }

    #[test]
    fn a_bare_keyframe_gets_the_parameter_sets() {
        let extradata = annex_b(&[&SPS, &PPS]);
        let keyframe = annex_b(&[&IDR]);
        let sent = with_parameter_sets(&keyframe, &extradata, MediaCodec::H264, true);
        assert_eq!(sent.into_owned(), annex_b(&[&SPS, &PPS, &IDR]));
    }

    #[test]
    fn a_bare_h265_keyframe_gets_the_parameter_sets() {
        let extradata = annex_b(&[&HEVC_VPS, &HEVC_SPS, &HEVC_PPS]);
        let keyframe = annex_b(&[&HEVC_IDR]);
        let sent = with_parameter_sets(&keyframe, &extradata, MediaCodec::H265, true);
        assert_eq!(
            sent.into_owned(),
            annex_b(&[&HEVC_VPS, &HEVC_SPS, &HEVC_PPS, &HEVC_IDR])
        );
    }

    #[test]
    fn a_keyframe_with_its_own_or_a_delta_frame_is_untouched() {
        let extradata = annex_b(&[&SPS, &PPS]);
        let complete = annex_b(&[&SPS, &PPS, &IDR]);
        let delta = annex_b(&[&[0x41, 6]]);
        assert!(matches!(
            with_parameter_sets(&complete, &extradata, MediaCodec::H264, true),
            Cow::Borrowed(_)
        ));
        assert!(matches!(
            with_parameter_sets(&delta, &extradata, MediaCodec::H264, false),
            Cow::Borrowed(_)
        ));
    }

    #[test]
    fn an_h265_keyframe_with_its_own_is_untouched() {
        let extradata = annex_b(&[&HEVC_VPS, &HEVC_SPS, &HEVC_PPS]);
        let complete = annex_b(&[&HEVC_VPS, &HEVC_SPS, &HEVC_PPS, &HEVC_IDR]);
        assert!(matches!(
            with_parameter_sets(&complete, &extradata, MediaCodec::H265, true),
            Cow::Borrowed(_)
        ));
    }

    #[test]
    fn an_avcc_header_is_not_prepended() {
        let avcc = [1, 0x64, 0, 0x1f, 0xff, 0xe1];
        let keyframe = annex_b(&[&IDR]);
        assert!(matches!(
            with_parameter_sets(&keyframe, &avcc, MediaCodec::H264, true),
            Cow::Borrowed(_)
        ));
    }
}
