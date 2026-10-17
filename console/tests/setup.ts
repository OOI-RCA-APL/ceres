// happy-dom has no `MediaError`, whose codes the video widget reads off a failed element.
globalThis.MediaError ??= {
  MEDIA_ERR_ABORTED: 1,
  MEDIA_ERR_NETWORK: 2,
  MEDIA_ERR_DECODE: 3,
  MEDIA_ERR_SRC_NOT_SUPPORTED: 4,
} as unknown as typeof MediaError

// Nor `getVideoPlaybackQuality`, which the video widget's stall check counts frames with. A test
// that plays frames defines its own on the element.
HTMLVideoElement.prototype.getVideoPlaybackQuality ??= function () {
  return { totalVideoFrames: 0 } as VideoPlaybackQuality
}
