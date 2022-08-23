export type ColorStop = {
  value: number
  color: string
}

export type Range = {
  min: number
  max: number
}

export type State = {
  value: string | boolean
  label: string
  color: string
}

export type BaseElementInfo = {
  name: string
}

export type GuageElementInfo = BaseElementInfo & {
  type: 'gauge'
  value: number
  unit?: string
  range: Range
  color?: ColorStop[] | string
}

export type NumberElementInfo = BaseElementInfo & {
  type: 'number'
  value: number
  unit?: string
  color?: ColorStop[] | string
}

export type BinaryStateElementInfo = BaseElementInfo & {
  type: 'binary'
  value: boolean
  options: State[]
}

export type ElementInfo = GuageElementInfo | NumberElementInfo | BinaryStateElementInfo

export function createColorStops(
  value: number,
  color: ColorStop[] | string | undefined,
  darkMode: boolean
) {
  if (color == null) {
    color = darkMode ? 'white' : 'black'
  }

  if (typeof color === 'string') {
    return [
      [0, color],
      [value, color],
    ]
  }

  const max = Math.max(...color.map((entry) => entry.value))
  return color.map((stop) => [stop.value / max, stop.color])
}
