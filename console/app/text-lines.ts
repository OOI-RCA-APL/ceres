/** Where each rendered line of text in an element ends, in px below the element's top.

Read from the text's own line boxes, so a cut at one of these offsets falls between lines whatever
margins, code spans or wrapping sit around them.
*/
export function lineBottoms(element: HTMLElement): number[] {
  const rects: DOMRect[] = []
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
  const range = document.createRange()
  for (let node = walker.nextNode(); node != null; node = walker.nextNode()) {
    range.selectNodeContents(node)
    rects.push(...Array.from(range.getClientRects()).filter((rect) => rect.height > 0))
  }
  rects.sort((a, b) => a.top - b.top)

  // A box whose middle sits above the current line's bottom shares that line, as a padded code
  // span does beside plain text.
  const bottoms: number[] = []
  for (const rect of rects) {
    const last = bottoms.at(-1)
    if (last == null || (rect.top + rect.bottom) / 2 > last) {
      bottoms.push(rect.bottom)
    } else {
      bottoms[bottoms.length - 1] = Math.max(last, rect.bottom)
    }
  }

  const top = element.getBoundingClientRect().top
  return bottoms.map((bottom) => bottom - top)
}
