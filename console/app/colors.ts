import type { Color } from '@/workspace/models'

/** How a button's fill is drawn, matching the variants `c-button` takes. */
export type ColorVariant = 'solid' | 'outline' | 'ghost'

/** The theme color a stored widget color renders as.

Stored workspaces keep the `positive`/`negative` vocabulary, so the conversion happens here on the
way to a component rather than by rewriting anyone's saved data. White and black stand outside the
palette and borrow `neutral`, `monochromeClasses` drawing them.
*/
export function semanticColor(
  color: Color,
): 'primary' | 'success' | 'warning' | 'error' | 'neutral' {
  if (color === 'positive') {
    return 'success'
  }
  if (color === 'negative') {
    return 'error'
  }
  if (color === 'white' || color === 'black') {
    return 'neutral'
  }

  return color
}

/** Classes drawing a button white or black, neither being a color the theme can name.

A solid fill sets its own text so the label stays legible against it, where an outlined or flat
button takes the color as its text and leaves the surface alone.
*/
export function monochromeClasses(color: Color, variant: ColorVariant): string | null {
  if (color !== 'white' && color !== 'black') {
    return null
  }

  if (variant === 'solid') {
    return color === 'white'
      ? 'bg-white text-black hover:bg-white/90 disabled:bg-white'
      : 'bg-black text-white hover:bg-black/90 disabled:bg-black'
  }

  const surface =
    color === 'white' ? 'text-white hover:bg-white/10' : 'text-black hover:bg-black/10'
  if (variant === 'ghost') {
    return surface
  }

  return `${surface} ${color === 'white' ? 'ring-white' : 'ring-black'}`
}
