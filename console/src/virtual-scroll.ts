/** Keep a virtual scroller drawing its rows while it is being scrolled.

Quasar recomputes which rows a virtual scroller should be showing from a `scroll` listener that is
debounced by 35ms, on the trailing edge only:

```js
const onVirtualScrollEvt = debounce(localOnVirtualScrollEvt, $q.platform.is.ios === true ? 120 : 35)
localScrollTarget.addEventListener('scroll', onVirtualScrollEvt, listenOpts.passive)
```

A scroll in progress fires an event about every frame, which is sooner than 35ms, so each event
clears the pending timer and starts another and the recompute never runs. It runs once the scroll
has been still for 35ms. Dragging the scrollbar or scrolling with momentum therefore leaves the
rows that were on screen when the scroll began, and then blank space once the scroller has moved
past them, until the moment it comes to rest. The records are all in memory, so nothing is being
waited for. Quasar considers this settled, so the timing is changed here instead.

The recompute is asked for once a frame while a scroll is in progress, which is as often as there
is any point in asking. That is a change of timing only, and no part of Quasar's own arithmetic is
touched. It is safe to run mid-scroll because the expensive half of the recompute already defers
itself to an animation frame and gives up when the scroll has moved on since:

```js
requestAnimationFrame(() => {
  if (prevScrollStart !== scrollDetails.scrollStart) return
  ...
  setScroll(scrollEl, scrollPosition, ...)
})
```

so the row range is updated every frame while the scroll position is only corrected once the
scroll settles, which is what keeps this from fighting a momentum scroll.

Reaching the debounced listener's payload is the awkward part, since it is held in a closure with
no way in. What the listener does have is a documented shape: it schedules its one piece of work
with `setTimeout`. So the listener is called with `setTimeout` briefly standing in for the real
one, which hands the work over rather than starting a timer, and it is then run directly. The
substitution spans a synchronous call that only ever schedules that one timer, so nothing else can
see it. If the shape ever changes, nothing is captured, and the listener goes back to being called
the way Quasar calls it.
*/

/** Quasar's debounced listeners carry a `cancel`, and it survives minification as a property. */
type DebouncedListener = EventListener & { cancel: () => void }

let installed = false

export function renderVirtualScrollWhileScrolling() {
  if (installed || typeof EventTarget === 'undefined') {
    return
  }

  installed = true

  const attach = EventTarget.prototype.addEventListener
  const detach = EventTarget.prototype.removeEventListener

  // What was put on in place of each listener, so taking it off again finds the same function.
  const standIns = new WeakMap<EventListener, EventListener>()

  EventTarget.prototype.addEventListener = function (type, listener, options) {
    return attach.call(this, type, standInFor(this, type, listener, standIns) ?? listener, options)
  }

  EventTarget.prototype.removeEventListener = function (type, listener, options) {
    const standIn = typeof listener === 'function' ? standIns.get(listener) : undefined
    return detach.call(this, type, standIn ?? listener, options)
  }
}

function standInFor(
  target: EventTarget,
  type: string,
  listener: EventListenerOrEventListenerObject | null,
  standIns: WeakMap<EventListener, EventListener>
): EventListener | null {
  if (!isVirtualScrollListener(target, type, listener)) {
    return null
  }

  const existing = standIns.get(listener)
  if (existing !== undefined) {
    return existing
  }

  const standIn = onceAFrame(listener)
  standIns.set(listener, standIn)

  return standIn
}

/** Whether this is the listener a virtual scroller watches its own scrolling with.

Asked of the element as well as the listener, since a debounced scroll listener on its own is also
what an infinite scroller attaches, and how often that one polls is the caller's to choose.
*/
function isVirtualScrollListener(
  target: EventTarget,
  type: string,
  listener: EventListenerOrEventListenerObject | null
): listener is DebouncedListener {
  return (
    type === 'scroll' &&
    typeof listener === 'function' &&
    typeof (listener as DebouncedListener).cancel === 'function' &&
    target instanceof Element &&
    target.classList.contains('q-virtual-scroll')
  )
}

/** Run `listener` on the first scroll of each frame, and once more after the last of them.

The trailing call matters as much as the leading one, since the frame a scroll ends on is where
the rows have to be right, and it is the one a plain throttle would drop.

Exported to be tested on its own. What it stands in for is decided by `isVirtualScrollListener`.
*/
export function onceAFrame(listener: DebouncedListener): EventListener {
  let pending = false
  let waiting: Event | null = null

  // Whether this listener still has the shape reaching its payload depends on. Asked once, and
  // answered by whether the first attempt captured anything. Held per listener, so one that turns
  // out to be built differently says nothing about the others.
  let payloadIsReachable = true

  function run(event: Event) {
    if (payloadIsReachable && !runNow(listener, event)) {
      payloadIsReachable = false
    }

    if (!payloadIsReachable) {
      // Its own timing, kept: the listener is called and then left alone for long enough that the
      // delay it is waiting out can actually elapse. Which is the whole trouble, since a scroller
      // that hears every scroll never stops starting its wait again.
      listener(event)
    }

    pending = true
    const gap = payloadIsReachable ? afterFrame : afterSettling
    gap(() => {
      pending = false

      if (waiting !== null) {
        const next = waiting
        waiting = null
        run(next)
      }
    })
  }

  return (event: Event) => {
    if (!pending) {
      run(event)
    } else {
      waiting = event
    }
  }
}

/** How long to wait for a frame that is not coming before carrying on without one. */
const longestFrameWait = 100

/** Long enough for a listener keeping its own time to have finished waiting and drawn.

Quasar waits 35ms, so this clears it with room to spare while still redrawing many times a second.
It does not clear the 120ms an iOS scroller waits, which is left exactly as it is today.
*/
const settlingWait = 50

function afterSettling(next: () => void) {
  setTimeout(next, settlingWait)
}

/** Run `next` on the next animation frame, or shortly afterwards if none arrives.

A document that is not being displayed is not painted either, so its animation frames never come.
Waiting on one alone would leave a scroller in a background tab holding a frame that will never
arrive and never drawing another row, which is worse than the debounce this replaces, since a
timer still fires in a tab nobody is looking at.
*/
function afterFrame(next: () => void) {
  let frame: number | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let done = false

  function ready() {
    if (done) {
      return
    }

    done = true

    if (frame !== null) {
      cancelAnimationFrame(frame)
    }
    if (timer !== null) {
      clearTimeout(timer)
    }

    next()
  }

  // Asked for only where there are frames to be had. Somewhere without them, such as a page being
  // rendered on the server, the wait below is the whole of it, and the caller is never left
  // holding a frame that is not coming.
  if (typeof requestAnimationFrame === 'function') {
    frame = requestAnimationFrame(ready)
  }

  timer = setTimeout(ready, longestFrameWait)
}

/** Call `listener` and run the work it schedules rather than waiting out its delay.

Answers whether there was any work to take over. A listener that scheduled nothing is not built the
way this expects, and is left to keep its own time from then on.
*/
function runNow(listener: DebouncedListener, event: Event): boolean {
  // Stood in for on `globalThis`, which is what an unqualified `setTimeout` call resolves to.
  const wait = globalThis.setTimeout
  let scheduled: (() => void) | null = null

  globalThis.setTimeout = ((handler: TimerHandler) => {
    if (typeof handler === 'function') {
      scheduled = handler as () => void
    }

    return 0
  }) as typeof globalThis.setTimeout

  try {
    listener(event)
  } finally {
    globalThis.setTimeout = wait
  }

  if (scheduled === null) {
    // Nothing was handed over, so the listener is not built the way this expects. The call above
    // did nothing, and this one lets it start its own timer as it meant to.
    listener(event)
    return false
  }

  ;(scheduled as () => void)()

  return true
}
