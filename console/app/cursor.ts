/** Make the browser look again at what the cursor should be, without the pointer having moved.

A browser settles the cursor when the pointer moves over something, not when the page changes its
mind about what that something should look like. So a rule that turns on with a held key leaves the
old cursor sitting there until the mouse is nudged, which reads as the key not having worked.

Forcing a different cursor onto the document for one frame and then dropping it makes the browser
resolve the cursor again from wherever the pointer already is. It is a nudge in place of the one
the user would otherwise have to give.
*/
export function refreshCursor() {
  const style = document.documentElement.style
  const held = style.cursor

  style.cursor = held === 'default' ? 'auto' : 'default'

  requestAnimationFrame(() => {
    style.cursor = held
  })
}
