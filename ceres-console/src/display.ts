import Zod from 'zod'

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
  value: Zod.union([Zod.string(), Zod.number()]),
  color: Zod.string(),
  icon: Zod.string().nullable().default(null),
  description: Zod.string().nullable().default(null),
})

export type IndicatorColor = Zod.infer<typeof IndicatorColorModel>
export const IndicatorColorModel = Zod.enum(['red', 'yellow', 'orange', 'blue', 'green'])

export type IndicatorSize = Zod.infer<typeof IndicatorSizeModel>
export const IndicatorSizeModel = Zod.enum(['xxs', 'xs', 'sm', 'md', 'lg', 'xl', 'xxl'])

export type BaseDisplayInfo = Zod.infer<typeof BaseDisplayInfoModel>
export const BaseDisplayInfoModel = Zod.object({})

export type NumberDisplayInfo = Zod.infer<typeof NumberDisplayInfoModel>
export const NumberDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('number'),
  value: Zod.number(),
  unit: Zod.string().nullable().default(null),
  color: Zod.union([Zod.array(ColorStopModel), Zod.string()])
    .nullable()
    .default(null),
})

export type StateDisplayInfo = Zod.infer<typeof StateDisplayInfoModel>
export const StateDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('state'),
  value: Zod.union([Zod.string(), Zod.number()]),
  options: Zod.array(StateModel),
  show_options: Zod.boolean(),
  vertical_icons: Zod.boolean(),
})

export type IndicatorDisplayInfo = Zod.infer<typeof IndicatorDisplayInfoModel>
export const IndicatorDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('indicator'),
  label: Zod.string(),
  value: Zod.boolean(),
  color: IndicatorColorModel,
  size: IndicatorSizeModel.nullable().default(null),
  reversed: Zod.boolean().default(false),
})

export type GuageDisplayInfo = Zod.infer<typeof GuageDisplayInfoModel>
export const GuageDisplayInfoModel = BaseDisplayInfoModel.extend({
  kind: Zod.literal('gauge'),
  value: Zod.number(),
  unit: Zod.string().nullable().default(null),
  range: RangeModel,
  color: Zod.union([Zod.array(ColorStopModel), Zod.string()])
    .nullable()
    .default(null),
})

export type DisplayInfo = Zod.infer<typeof DisplayInfoModel>
export const DisplayInfoModel = Zod.discriminatedUnion('kind', [
  NumberDisplayInfoModel,
  StateDisplayInfoModel,
  IndicatorDisplayInfoModel,
  GuageDisplayInfoModel,
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
