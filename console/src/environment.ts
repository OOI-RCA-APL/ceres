const userAgent = navigator.userAgent.toLowerCase()
export const isSafari =
  (userAgent.includes('safari') || userAgent.includes('iphone') || userAgent.includes('ipad')) &&
  !userAgent.includes('chrome')

function computeIsMediaSourceSupported() {
  try {
    new MediaSource()
    return true
  } catch (error) {
    return false
  }
}

export const isMediaSourceSupported = computeIsMediaSourceSupported()
