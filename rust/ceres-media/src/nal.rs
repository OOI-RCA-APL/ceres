//! The NAL units of H.264 and H.265 access units in Annex B form, the form an RTSP source and
//! the H.264 encoder both give.

use crate::MediaCodec;

/// The NAL units of an Annex B access unit, without their start codes.
pub struct NalUnits<'a>(pub &'a [u8]);

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

/// Whether no other frame references the Annex B access unit `data`, so dropping it leaves
/// the rest decodable.
///
/// That holds when every slice says so, H.264 with a zero `nal_ref_idc` and H.265 with a
/// sub-layer non-reference type, the even ones up to 14. Only slices count, since parameter
/// sets and SEI carry no reference flag of their own.
pub fn is_unreferenced(data: &[u8], codec: MediaCodec) -> bool {
    let mut slices = NalUnits(data)
        .filter_map(|unit| unit.first().copied())
        .filter_map(|header| match codec {
            // Types 1 to 5 are slices, the reference flag in the two bits above the type.
            MediaCodec::H264 => (1..=5)
                .contains(&(header & 0x1f))
                .then_some((header >> 5) & 0x3 == 0),
            // Types 0 to 31 are slices.
            MediaCodec::H265 => {
                let kind = (header >> 1) & 0x3f;
                (kind <= 31).then_some(kind <= 14 && kind % 2 == 0)
            }
            MediaCodec::Other => Some(false),
        })
        .peekable();
    slices.peek().is_some() && slices.all(|unreferenced| unreferenced)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn annex_b(units: &[&[u8]]) -> Vec<u8> {
        units
            .iter()
            .flat_map(|unit| [&[0, 0, 0, 1][..], unit].concat())
            .collect()
    }

    #[test]
    fn splits_units_at_either_start_code() {
        let (sps, pps, idr) = ([0x67, 1, 2], [0x68, 3], [0x65, 4, 5]);
        let data = [
            &[0, 0, 0, 1][..],
            &sps,
            &[0, 0, 1],
            &pps,
            &[0, 0, 0, 1],
            &idr,
        ]
        .concat();
        let units: Vec<&[u8]> = NalUnits(&data).collect();
        assert_eq!(units, [&sps[..], &pps, &idr]);
    }

    #[test]
    fn an_h264_frame_is_unreferenced_when_every_slice_is() {
        // SEI, and a B slice with `nal_ref_idc` zero.
        let sei = [0x06, 5];
        let b_slice = [0x01, 7];
        assert!(is_unreferenced(
            &annex_b(&[&sei, &b_slice]),
            MediaCodec::H264
        ));
        // A reference B slice, `nal_ref_idc` two.
        let reference = [0x41, 7];
        let mixed = annex_b(&[&sei, &b_slice, &reference]);
        assert!(!is_unreferenced(&mixed, MediaCodec::H264));
        assert!(!is_unreferenced(&annex_b(&[&[0x65, 4]]), MediaCodec::H264));
        // Parameter sets and SEI alone carry no picture to drop.
        assert!(!is_unreferenced(&annex_b(&[&sei]), MediaCodec::H264));
    }

    #[test]
    fn an_h265_frame_is_unreferenced_when_its_slices_are_sub_layer_non_reference() {
        let trail_n = [0, 1, 7];
        let trail_r = [1 << 1, 1, 7];
        let idr = [19 << 1, 1, 4];
        let sei = [39 << 1, 1, 5];
        assert!(is_unreferenced(
            &annex_b(&[&sei, &trail_n]),
            MediaCodec::H265
        ));
        assert!(!is_unreferenced(&annex_b(&[&trail_r]), MediaCodec::H265));
        assert!(!is_unreferenced(&annex_b(&[&idr]), MediaCodec::H265));
    }
}
