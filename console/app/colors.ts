import type { Color } from '@/workspace/models'

/** The theme color a stored widget color renders as.

Stored workspaces keep the `positive`/`negative` vocabulary, so the conversion happens here on the
way to a component rather than by rewriting anyone's saved data.
*/
export function semanticColor(color: Color): 'primary' | 'success' | 'warning' | 'error' {
  if (color === 'positive') {
    return 'success'
  }
  if (color === 'negative') {
    return 'error'
  }

  return color
}
