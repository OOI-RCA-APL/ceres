/** A note a widget sends up for its header, such as the transport a video plays over. */
export type WidgetStatus = {
  text: string
  /** Set for live media: `'live'` at the newest frame, `'behind'` when paused or lagging. */
  live?: 'live' | 'behind'
  /** Brings live media back to its newest frame. */
  goLive?: () => void
}
