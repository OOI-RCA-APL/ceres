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
  series: string[]
}

/** The tokens a series takes its color from, in the order series are drawn. */
const seriesTokens = [
  '--console-series-1',
  '--console-series-2',
  '--console-series-3',
  '--console-series-4',
  '--console-series-5',
  '--console-series-6',
  '--console-series-7',
]

/** The color a series in `index` position takes when nothing has been chosen for it.

Wraps rather than running out, since a chart may carry more series than the theme names colors.
*/
export function defaultSeriesColor(index: number): string {
  const palette = chartPalette().series
  return palette[index % palette.length] ?? '#007dab'
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
    series: seriesTokens.map(token).filter((color) => color !== ''),
  }
}

/** An echarts theme object built from `palette`.

Covers the series colors and the chrome around them: text, axes, split lines, and tooltips.
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
    color: palette.series,
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
