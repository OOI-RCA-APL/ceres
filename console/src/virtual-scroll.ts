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

/** Draw on every scroll, taking over the work the listener would have put off.

Nothing is coalesced here. A browser already fires at most one scroll event per frame, holding
them back until it is about to paint, so a gate of our own would only ever make a scroller draw
less often than it is asked to and never more rarely than it should.

A listener whose work could not be taken over is a different matter, and is only called as often
as its own delay can actually elapse between calls. Calling that one on every scroll is exactly
what stops it ever drawing.

Exported to be tested on its own. What it stands in for is decided by `isVirtualScrollListener`.
*/
export function onceAFrame(listener: DebouncedListener): EventListener {
  // Whether this listener still has the shape reaching its work depends on. Asked once, and
  // answered by whether the first attempt captured anything. Held per listener, so one that turns
  // out to be built differently says nothing about the others.
  let payloadIsReachable = true

  let waiting: Event | null = null
  let settling = false

  function settle() {
    settling = false

    if (waiting !== null) {
      const next = waiting
      waiting = null
      keepingItsOwnTime(next)
    }
  }

  function keepingItsOwnTime(event: Event, alreadyCalled: boolean = false) {
    if (settling) {
      waiting = event
      return
    }

    settling = true
    if (!alreadyCalled) {
      listener(event)
    }

    setTimeout(settle, settlingWait)
  }

  return (event: Event) => {
    if (payloadIsReachable) {
      if (runNow(listener, event)) {
        return
      }

      // Finding out cost this event a call of its own, which `runNow` has already made, so all
      // that is left is to give the delay it started room to elapse.
      payloadIsReachable = false
      keepingItsOwnTime(event, true)
      return
    }

    keepingItsOwnTime(event)
  }
}

/** Long enough for a listener keeping its own time to have finished waiting and drawn.

Quasar waits 35ms, so this clears it with room to spare while still redrawing many times a second.
It does not clear the 120ms an iOS scroller waits, which is left exactly as it is today.
*/
const settlingWait = 50

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
