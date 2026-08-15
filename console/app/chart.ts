import type { EChartsOption } from 'echarts'

export type Option = EChartsOption
export type DataValue = string | number | Date | null | undefined | DataValue[]

/** The theme tokens a chart reads, resolved from the document so they follow color mode. */
export type ChartPalette = {
  text: string
  textMuted: string
  border: string
  borderMuted: string
  backgroundElevated: string
}

/** Resolve the token palette from the document's computed styles.

Charts init with a theme built from these rather than echarts' own light and dark themes, so
they follow the app's color mode exactly. Callers re-read on color mode changes.
*/
export function chartPalette(): ChartPalette {
  const styles = getComputedStyle(document.documentElement)
  const token = (name: string) => styles.getPropertyValue(name).trim()

  return {
    text: token('--ui-text'),
    textMuted: token('--ui-text-muted'),
    border: token('--ui-border-accented'),
    borderMuted: token('--ui-border'),
    backgroundElevated: token('--ui-bg-elevated'),
  }
}

/** An echarts theme object built from `palette`.

Series colors stay echarts' defaults, which hold up on both modes. The theme covers the
chrome: text, axes, split lines, and tooltips.
*/
export function chartTheme(palette: ChartPalette): object {
  const axis = {
    axisLine: { lineStyle: { color: palette.border } },
    axisTick: { lineStyle: { color: palette.border } },
    axisLabel: { color: palette.textMuted },
    nameTextStyle: { color: palette.textMuted },
    splitLine: { lineStyle: { color: palette.borderMuted } },
    splitArea: { areaStyle: { color: ['transparent', `${palette.borderMuted}40`] } },
  }

  return {
    textStyle: { color: palette.textMuted },
    title: { textStyle: { color: palette.text } },
    legend: { textStyle: { color: palette.textMuted } },
    categoryAxis: axis,
    valueAxis: axis,
    timeAxis: axis,
    logAxis: axis,
    tooltip: {
      backgroundColor: palette.backgroundElevated,
      borderColor: palette.borderMuted,
      textStyle: { color: palette.text },
    },
  }
}
