# Vendored Sources

`build.rs` builds these releases offline, so a source distribution needs no network.

- `ffmpeg-9.0.2.tar.xz` is the FFmpeg release tarball, unchanged, from
  https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz (SHA-256
  `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`). LGPL-2.1-or-later as
  configured.
- `openh264-2.6.0.tar.xz` is the OpenH264 v2.6.0 source archive from
  https://github.com/cisco/openh264/archive/refs/tags/v2.6.0.tar.gz (SHA-256
  `558544ad358283a7ab2930d69a9ceddf913f4a51ee9bf1bfb9e377322af81a69`), repacked without its
  `res/` test bitstreams, which are 60 MB of the 61 MB archive and unused by the build.
  BSD-2-Clause.

To repack an OpenH264 release after updating `OPENH264_VERSION`:

```sh
tar xzf openh264-<version>.tar.gz
COPYFILE_DISABLE=1 tar --no-mac-metadata --uid 0 --gid 0 --uname '' --gname '' \
    -cJf openh264-<version>.tar.xz --exclude 'openh264-<version>/res' openh264-<version>
```
