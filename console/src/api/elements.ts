import { Address } from '@/api/address'
import Zod from 'zod'

export type BaseElement = Zod.infer<typeof BaseElementModel>
export const BaseElementModel = Zod.object({
  css_style: Zod.union([Zod.string(), Zod.record(Zod.string(), Zod.string())])
    .nullable()
    .default(null),
  css_class: Zod.union([Zod.string(), Zod.array(Zod.string())])
    .nullable()
    .default(null),
})

export type ButtonElement = Zod.infer<typeof ButtonElementModel>
export const ButtonElementModel = BaseElementModel.extend({
  type: Zod.literal('button'),
  title: Zod.string(),
  address: Zod.string().transform(Address.parse),
  action: Zod.string(),
  color: Zod.string().optional().nullable(),
})

export type Justify = Zod.infer<typeof JustifyModel>
export const JustifyModel = Zod.enum(['start', 'center', 'end', 'space-between', 'space-evenly'])

export type Align = Zod.infer<typeof AlignModel>
export const AlignModel = Zod.enum(['start', 'center', 'end'])

export type Sizing = Zod.infer<typeof SizingModel>
export const SizingModel = Zod.enum(['shrink', 'grow'])

export type AtomicValue = Zod.infer<typeof AtomicValueModel>
export const AtomicValueModel = Zod.union([Zod.boolean(), Zod.number(), Zod.string()])

export type ColorStop = Zod.infer<typeof ColorStopModel>
export const ColorStopModel = Zod.object({
  value: Zod.number(),
  color: Zod.string(),
})

export type StateElementOption = Zod.infer<typeof StateElementOptionModel>
export const StateElementOptionModel = BaseElementModel.extend({
  value: AtomicValueModel,
  label: Zod.string(),
  color: Zod.string(),
  icon: Zod.string().nullable().default(null),
  description: Zod.string().nullable().default(null),
})

type BoxElement = BaseElement & {
  sizing: Sizing
  justify: Justify
  align: Align
  children: Element[]
}

const BoxModelElement = {
  sizing: SizingModel.default('grow'),
  justify: JustifyModel.default('start'),
  align: AlignModel.default('start'),
  children: Zod.lazy(() => Zod.array(ElementModel)),
}

export type RowElement = BoxElement & {
  type: 'row'
}

export const RowElementModel = BaseElementModel.extend({
  type: Zod.literal('row'),
  ...BoxModelElement,
}) as Zod.ZodType<RowElement>

export type ColumnElement = BoxElement & {
  type: 'column'
}

export const ColumnElementModel = BaseElementModel.extend({
  type: Zod.literal('column'),
  ...BoxModelElement,
}) as Zod.ZodType<ColumnElement>

export type CarouselElement = BaseElement & {
  type: 'carousel'
  children: Element[]
  height?: number | string | null
}

export const CarouselElementModel = BaseElementModel.extend({
  type: Zod.literal('carousel'),
  height: Zod.union([Zod.string(), Zod.number()]).optional().nullable(),
  children: Zod.lazy(() => Zod.array(ElementModel)),
}) as Zod.ZodType<CarouselElement>

export type TextVariant = Zod.infer<typeof TextVariantModel>
export const TextVariantModel = Zod.enum([
  'title1',
  'title2',
  'title3',
  'body1',
  'body2',
  'th',
  'description',
  'value',
])

export type TextElement = Zod.infer<typeof TextElementModel>
export const TextElementModel = BaseElementModel.extend({
  type: Zod.literal('text'),
  variant: TextVariantModel.default('value'),
  value: Zod.string(),
  color: Zod.string().nullable().default(null),
})

export type HTMLElement = Zod.infer<typeof HTMLElementModel>
export const HTMLElementModel = BaseElementModel.extend({
  type: Zod.literal('html'),
  value: Zod.string(),
})

export type StateElement = Zod.infer<typeof StateElementModel>
export const StateElementModel = BaseElementModel.extend({
  type: Zod.literal('state'),
  value: AtomicValueModel,
  options: Zod.array(StateElementOptionModel),
})

export type GaugeElement = Zod.infer<typeof GaugeElementModel>
export const GaugeElementModel = BaseElementModel.extend({
  type: Zod.literal('gauge'),
  value: Zod.number(),
  unit: Zod.string().nullable().default(null),
  min: Zod.number(),
  max: Zod.number(),
  color: Zod.union([Zod.array(ColorStopModel), Zod.string()])
    .nullable()
    .default(null),
})

export type ChartElement = Zod.infer<typeof ChartElementModel>
export const ChartElementModel = BaseElementModel.extend({
  type: Zod.literal('chart'),
  value: Zod.record(Zod.string(), Zod.any()),
  height: Zod.union([Zod.number(), Zod.string()]).nullable().default(null),
})

export type RenderElement = Zod.infer<typeof RenderElementModel>
export const RenderElementModel = BaseElementModel.extend({
  type: Zod.literal('display'),
  address: Zod.string().transform(Address.parse),
  query: Zod.string(),
})

export type DisplayElement = Zod.infer<typeof DisplayElementModel>
export const DisplayElementModel = BaseElementModel.extend({
  type: Zod.literal('display'),
  title: Zod.string(),
  address: Zod.string().transform(Address.parse),
  query: Zod.string(),
})

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

export type Element =
  | ButtonElement
  | RowElement
  | ColumnElement
  | CarouselElement
  | TextElement
  | HTMLElement
  | StateElement
  | GaugeElement
  | ChartElement
  | DisplayElement

export const ElementModel: Zod.ZodType<Element> = Zod.discriminatedUnion('type', [
  ButtonElementModel,
  RowElementModel,
  ColumnElementModel,
  CarouselElementModel,
  TextElementModel,
  HTMLElementModel,
  StateElementModel,
  GaugeElementModel,
  ChartElementModel,
  DisplayElementModel,
] as any)

export type ElementType = Element['type']
