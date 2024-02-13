import Color from 'color'
import { colors } from 'quasar'

export function getColor(color: string): string {
  return colors.getPaletteColor(color)
}

export function getColorClasses(backgroundColor: string | null): string {
  return `${getBackgroundColorClass(backgroundColor) ?? ''} ${getForegroundColorClass(
    backgroundColor
  )}`
}

export function getBackgroundColorClass(color: string | null): string | null {
  if (color == null) {
    return null
  }

  return `bg-${color}`
}

export function getForegroundColor(backgroundColor: string | null): string {
  return isDark(backgroundColor ?? 'black') ? 'white' : 'black'
}

export function getForegroundColorClass(backgroundColor: string | null): string {
  return `text-${getForegroundColor(backgroundColor)}`
}

export function changeColor(color: string): Color {
  return Color(colors.getPaletteColor(color))
}

export function isDark(color: string): boolean {
  return Color(colors.getPaletteColor(color)).darken(0.25).isDark()
}
