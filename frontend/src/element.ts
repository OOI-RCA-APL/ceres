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
  icon?: string
  description?: string
}

export type IndicatorColor = 'red' | 'yellow' | 'orange' | 'blue' | 'green'
export type IndicatorSize = 'xxs' | 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'

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

export type StateElementInfo = BaseElementInfo & {
  type: 'state'
  value: string | number
  options: State[]
  showOptions?: boolean
  verticalIcons: boolean
}

export type IndicatorElementInfo = BaseElementInfo & {
  type: 'indicator'
  label: string
  value: boolean
  color: IndicatorColor
  size?: IndicatorSize
  reversed?: boolean
}

export type ElementInfo =
  | GuageElementInfo
  | IndicatorElementInfo
  | NumberElementInfo
  | StateElementInfo

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
