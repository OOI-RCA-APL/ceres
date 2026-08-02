import { nextTick } from 'vue'

/** Pointer-driven reordering, the way browser tabs behave.

The held item tracks the pointer, its neighbours slide aside as it passes their midpoints, and it
settles into the gap when released. Positions are measured once when the drag begins and every
offset is derived from those, so nothing depends on layout that is mid-animation.

The same behavior serves a horizontal tab strip and a vertical list, which is why the axis is a
parameter rather than two implementations that drift apart.
*/
export type ReorderAxis = 'horizontal' | 'vertical'

type Placement = { start: number; size: number }

type Drag = {
  index: number
  pointerId: number
  origin: number
  placements: Placement[]
  moved: boolean
  /** Where the list was scrolled to when the drag began, which every offset is measured against. */
  originScroll: number
  /** Where the pointer was last seen, so the edge scroll can carry on without it moving. */
  pointer: number
}

const dragThreshold = 4
const settleDuration = 140

// How near the end of a scrolling list the pointer has to be for the list to start travelling.
const edgeZone = 56

// How far the list travels each millisecond with the pointer right at the edge, and the least it
// creeps anywhere inside the zone. In between it eases between the two, so resting just inside
// nudges the list along and pushing to the very edge sends it.
const edgeSpeed = 2.2
const edgeCrawl = 0.05

// The longest stretch of time the list will cover in one go. Anything longer than this is the page
// having been left alone rather than the list running slowly, and carrying that whole distance
// over would fling it the moment the page came back.
const longestStep = 32

export function usePointerReorder(options: {
  axis: ReorderAxis
  /** Elements being reordered, in their current visual order. */
  elements: () => HTMLElement[]
  onReorder: (from: number, to: number) => void

  /** Offer the release to somewhere outside this list, before it is treated as a reorder.

  Returning true means the drop belonged elsewhere, so nothing here is reordered and the held item
  simply lets go. The pointer is captured by the row being dragged, so this is called wherever on
  the page the release happens, and `event` carries the coordinates to test against.

  It is called before the held item settles, so a handler is free to open a dialog rather than
  leaving a row hanging under a modal.
  */
  onDrop?: (index: number, event: PointerEvent) => boolean

  /** The box the items scroll inside, for a list longer than the room it has.

  Held near either end it travels, so an item can be taken further than the visible stretch of the
  list. Without one the list is taken to show everything it holds.
  */
  scroller?: () => HTMLElement | null
}) {
  const horizontal = $computed(() => options.axis === 'horizontal')

  let drag = $ref<Drag | null>(null)
  let offset = $ref(0)
  let target = $ref(0)
  let settling = $ref(false)
  let swapping = $ref(false)
  let suppressClick = false
  let travelling: number | null = null
  let lastTravel = 0

  function scrollOf(): number {
    const element = options.scroller?.()
    if (element == null) {
      return 0
    }

    return horizontal ? element.scrollLeft : element.scrollTop
  }

  function measure(element: HTMLElement): Placement {
    const box = element.getBoundingClientRect()

    if (horizontal) {
      return { start: box.left, size: box.width }
    }

    return { start: box.top, size: box.height }
  }

  function coordinate(event: PointerEvent): number {
    return horizontal ? event.clientX : event.clientY
  }

  function onPointerDown(index: number, event: PointerEvent) {
    suppressClick = false

    // A drag should only ever start from a plain left press.
    if (event.button !== 0) {
      return
    }

    const elements = options.elements()

    // An item's own buttons own their presses, so a tab is not dragged by its close button. The
    // item itself is exempt, since a carousel dot is a button and is the very thing being dragged.
    const pressed = (event.target as HTMLElement).closest('button')
    if (pressed != null && pressed !== elements[index]) {
      return
    }

    const placements = elements.map(measure)
    if (placements.length === 0) {
      return
    }

    drag = {
      index,
      pointerId: event.pointerId,
      origin: coordinate(event),
      placements,
      moved: false,
      originScroll: scrollOf(),
      pointer: coordinate(event),
    }
    offset = 0
    target = index
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)

    document.body.classList.add('reordering')
    lastTravel = performance.now()
    travelling = requestAnimationFrame(travel)
  }

  /** Carry the list along while the pointer rests near either end of it.

  The pointer can stop moving and still be asking for more, so this runs on its own rather than off
  pointer events, and stops the moment the list can go no further.
  */
  function travel(now: number) {
    const elapsed = Math.min(now - lastTravel, longestStep)
    lastTravel = now
    travelling = requestAnimationFrame(travel)

    const element = options.scroller?.()
    if (drag == null || !drag.moved || element == null) {
      return
    }

    const box = element.getBoundingClientRect()
    const near = horizontal ? box.left : box.top
    const far = horizontal ? box.right : box.bottom

    // How far into the zone the pointer has pushed, from nothing at its inner boundary to all of
    // it at the edge. Squaring that keeps the first part of the zone gentle and saves the speed
    // for the last few pixels, so the list is easy to nudge and still quick to send.
    let depth = 0
    let direction = 0
    if (drag.pointer < near + edgeZone) {
      depth = (near + edgeZone - drag.pointer) / edgeZone
      direction = -1
    } else if (drag.pointer > far - edgeZone) {
      depth = (drag.pointer - (far - edgeZone)) / edgeZone
      direction = 1
    }

    if (direction === 0) {
      return
    }

    const eased = Math.min(depth, 1) ** 2
    const step = direction * Math.max(edgeCrawl, eased * edgeSpeed) * elapsed

    if (horizontal) {
      element.scrollLeft += step
    } else {
      element.scrollTop += step
    }

    apply()
  }

  /** Place the held item and work out where it would land, from wherever the pointer last was.

  Taken from the list's scroll as well as the pointer, since a list travelling under a still
  pointer moves the item along just as surely as the pointer does.
  */
  function apply() {
    if (drag == null) {
      return
    }

    const delta = drag.pointer - drag.origin + (scrollOf() - drag.originScroll)
    offset = delta
    target = resolveTarget(delta)
  }

  function onPointerMove(event: PointerEvent) {
    if (drag == null || event.pointerId !== drag.pointerId || settling) {
      return
    }

    drag.pointer = coordinate(event)

    const delta = drag.pointer - drag.origin + (scrollOf() - drag.originScroll)
    if (!drag.moved && Math.abs(delta) < dragThreshold) {
      return
    }

    drag.moved = true
    apply()
  }

  /** Return the index the held item would land on, given how far it has travelled. */
  function resolveTarget(delta: number): number {
    if (drag == null) {
      return 0
    }

    const { index, placements } = drag
    const center = placements[index].start + placements[index].size / 2 + delta

    let landing = index
    while (
      landing > 0 &&
      center < placements[landing - 1].start + placements[landing - 1].size / 2
    ) {
      landing--
    }
    while (
      landing < placements.length - 1 &&
      center > placements[landing + 1].start + placements[landing + 1].size / 2
    ) {
      landing++
    }

    return landing
  }

  /** Return how far an item slides aside to open the gap the held one is heading for. */
  function shiftFor(index: number): number {
    if (drag == null || index === drag.index) {
      return 0
    }

    const size = drag.placements[drag.index].size
    if (drag.index < target && index > drag.index && index <= target) {
      return -size
    }
    if (drag.index > target && index >= target && index < drag.index) {
      return size
    }

    return 0
  }

  /** Return where the held item comes to rest, which is the near edge of the gap it opened. */
  function settledOffset(): number {
    if (drag == null) {
      return 0
    }

    const { index, placements } = drag
    if (target > index) {
      const landing = placements[target]
      const held = placements[index]
      return landing.start + landing.size - (held.start + held.size)
    }
    if (target < index) {
      return placements[target].start - placements[index].start
    }

    return 0
  }

  function styleFor(index: number) {
    if (drag == null) {
      return undefined
    }

    const distance = index === drag.index ? (settling ? settledOffset() : offset) : shiftFor(index)
    const translate = horizontal ? `translateX(${distance}px)` : `translateY(${distance}px)`
    return { transform: translate }
  }

  async function onPointerUp(event: PointerEvent) {
    if (drag == null || event.pointerId !== drag.pointerId) {
      return
    }

    if (travelling != null) {
      cancelAnimationFrame(travelling)
      travelling = null
    }

    document.body.classList.remove('reordering')

    if (!drag.moved) {
      drag = null
      return
    }

    // Somewhere else may claim the release, in which case this list lets go without reordering and
    // without the settle animation, since the row is about to be gone or spoken for.
    if (options.onDrop?.(drag.index, event) === true) {
      suppressClick = true
      drag = null
      offset = 0
      return
    }

    const from = drag.index
    const to = target

    // Let the held item travel into its gap before the list reorders underneath it, otherwise it
    // jumps the remaining distance the instant the transform is dropped.
    suppressClick = true
    settling = true
    await new Promise((resolve) => setTimeout(resolve, settleDuration))

    // Dropping the offsets and reordering the list happen in the same frame, and the items that
    // slid aside are already standing where the new order puts them. Animating that frame would
    // replay the slide they just finished, so transitions are off across the swap and restored
    // after the browser has painted it.
    settling = false
    swapping = true
    drag = null
    offset = 0

    if (to !== from) {
      options.onReorder(from, to)
    }

    await nextTick()
    requestAnimationFrame(() => requestAnimationFrame(() => (swapping = false)))
  }

  /** Whether the click that follows a drag should be swallowed, so releasing does not also
  activate whatever was being dragged.
  */
  function consumeClick(): boolean {
    if (suppressClick) {
      suppressClick = false
      return true
    }

    return false
  }

  return {
    handlers: (index: number) => ({
      onPointerdown: (event: PointerEvent) => onPointerDown(index, event),
      onPointermove: onPointerMove,
      onPointerup: onPointerUp,
      onPointercancel: onPointerUp,
    }),
    styleFor,
    consumeClick,
    isHeld: (index: number) => drag?.index === index,
    isGrabbed: (index: number) => drag?.index === index && !settling,
    get isDragging() {
      return drag != null
    },
    get isSwapping() {
      return swapping
    },
  }
}

/** Move an item from one index to another, returning a new array. */
export function moved<T>(items: T[], from: number, to: number): T[] {
  const result = [...items]
  const [item] = result.splice(from, 1)
  result.splice(to, 0, item)
  return result
}
