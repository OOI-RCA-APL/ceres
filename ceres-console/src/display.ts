import Zod from 'zod'

export type AtomicValue = Zod.infer<typeof AtomicValueModel>
export const AtomicValueModel = Zod.union([Zod.boolean(), Zod.number(), Zod.string()])

export type ColorStop = Zod.infer<typeof ColorStopModel>
export const ColorStopModel = Zod.object({
  value: Zod.number(),
  color: Zod.string(),
})

export type Range = Zod.infer<typeof RangeModel>
export const RangeModel = Zod.object({
  min: Zod.number(),
  max: Zod.number(),
})

export type State = Zod.infer<typeof StateModel>
export const StateModel = Zod.object({
  value: AtomicValueModel,
  label: Zod.string(),
  color: Zod.string(),
  icon: Zod.string().nullable().default(null),
  description: Zod.string().nullable().default(null),
})

export type BaseDisplayInfo = Zod.infer<typeof BaseDisplayInfoModel>
export const BaseDisplayInfoModel = Zod.object({})

export type ValueDisplayInfo = Zod.infer<typeof ValueDisplayInfoModel>
export const ValueDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('value'),
  value: AtomicValueModel,
  unit: Zod.string().nullable().default(null),
  color: Zod.string().nullable().default(null),
})

export type StateDisplayInfo = Zod.infer<typeof StateDisplayInfoModel>
export const StateDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('state'),
  value: AtomicValueModel,
  options: Zod.array(StateModel),
})

export type GaugeDisplayInfo = Zod.infer<typeof GaugeDisplayInfoModel>
export const GaugeDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('gauge'),
  value: Zod.number(),
  unit: Zod.string().nullable().default(null),
  range: RangeModel,
  color: Zod.union([Zod.array(ColorStopModel), Zod.string()])
    .nullable()
    .default(null),
})

export type ChartDisplayInfo = Zod.infer<typeof ChartDisplayInfoModel>
export const ChartDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('chart'),
  value: Zod.record(Zod.string(), Zod.any()),
  height: Zod.number(),
})

export type DisplayInfo = Zod.infer<typeof DisplayInfoModel>
export const DisplayInfoModel = Zod.discriminatedUnion('kind', [
  ValueDisplayInfoModel,
  StateDisplayInfoModel,
  GaugeDisplayInfoModel,
  ChartDisplayInfoModel,
])

export function createColorStops(
  value: number,
  color: ColorStop[] | string | undefined | null,
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
