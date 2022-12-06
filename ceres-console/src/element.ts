export type ColorStop = {
  value: number
  color: string
}

export type Range = {
  min: number
  max: number
}

export type State = {
  value: string | number
  color: string
  icon?: string | null
  description?: string | null
}

export type IndicatorColor = 'red' | 'yellow' | 'orange' | 'blue' | 'green'
export type IndicatorSize = 'xxs' | 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'

export type BaseElementInfo = {
  name: string
}

export type NumberElementInfo = BaseElementInfo & {
  type: 'number'
  value: number
  unit?: string | null
  color?: ColorStop[] | string | null
}

export type StateElementInfo = BaseElementInfo & {
  type: 'state'
  value: string | number
  options: State[]
  show_options: boolean
  vertical_icons: boolean
}

export type IndicatorElementInfo = BaseElementInfo & {
  type: 'indicator'
  label: string
  value: boolean
  color: IndicatorColor
  size?: IndicatorSize | null
  reversed?: boolean | null
}

export type GuageElementInfo = BaseElementInfo & {
  type: 'gauge' | 'halfgauge'
  value: number
  unit?: string | null
  range: Range
  color?: ColorStop[] | string | null
}

export type ElementInfo =
  | NumberElementInfo
  | StateElementInfo
  | IndicatorElementInfo
  | GuageElementInfo

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
