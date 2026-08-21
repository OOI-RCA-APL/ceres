import { omit, orderBy } from 'lodash-es'
import { v7 } from 'uuid'
import * as z from 'zod'

import { Address, AddressModel, AddressSelectorModel, engineRoot } from '@/api/address'
import { AlertFilterModel } from '@/api/alerts'
import { ProcedureTypeModel } from '@/api/components'
import { LogEntryFilterModel } from '@/api/logs'
import { MessageFilterModel } from '@/api/messages'
import { ParticleFilterModel } from '@/api/particles'
import { DateTimeModel } from '@/api/shared'
import { FilterQueryModel } from '@/filters/model'
import { safeArrayOf } from '@/utilities'

export type BaseWidget = z.infer<typeof BaseWidgetModel>
export const BaseWidgetModel = z.object({
  id: z.string().catch(() => v7()),
  name: z.string(),
  // Fraction of row width out of 120, not pixels.
  width: z.number().catch(() => widgetWidthSubdivisions),
  restricted: z.boolean().catch(false),

  // Whether the widget renders without a card and header around it. Its content is all that
  // shows, and the drag handle appears over it on hover.
  frameless: z.boolean().catch(false),
})

export type MessageDataDisplay = z.infer<typeof MessageDataDisplayModel>
export const MessageDataDisplayModel = z.enum(['default', 'hex', 'binary']).catch('default')

/** The columns a record view leaves out, named as the view's own column definitions name them. */
const HiddenColumnsModel = z
  .string()
  .array()
  .catch(() => [])

export type MessagesWidget = z.infer<typeof MessagesWidgetModel>
export const MessagesWidgetModel = BaseWidgetModel.extend({
  type: z.literal('messages'),
  name: z.string().catch('Messages'),
  filter: MessageFilterModel.catch(() => ({})),
  query: FilterQueryModel.catch(() => []),
  hiddenColumns: HiddenColumnsModel,
  dataDisplay: MessageDataDisplayModel,
  commandAddress: AddressModel.nullish(),
  commandConnection: z.string().nullish(),
  commandText: z.string().catch(''),
  commandHistory: z
    .string()
    .array()
    .catch(() => []),
  commandHistoryIndex: z.number().nullish().catch(undefined),
})

export type ParticlesWidget = z.infer<typeof ParticlesWidgetModel>
export const ParticlesWidgetModel = BaseWidgetModel.extend({
  type: z.literal('particles'),
  name: z.string().catch('Particles'),
  filter: ParticleFilterModel.catch(() => ({})),
  query: FilterQueryModel.catch(() => []),
  hiddenColumns: HiddenColumnsModel,
})

export type AlertsWidget = z.infer<typeof AlertsWidgetModel>
export const AlertsWidgetModel = BaseWidgetModel.extend({
  type: z.literal('alerts'),
  name: z.string().catch('Alerts'),
  filter: AlertFilterModel.catch(() => ({})),
  query: FilterQueryModel.catch(() => []),
  hiddenColumns: HiddenColumnsModel,
})

export type LogsWidget = z.infer<typeof LogsWidgetModel>
export const LogsWidgetModel = BaseWidgetModel.extend({
  type: z.literal('logs'),
  name: z.string().catch('Logs'),
  filter: LogEntryFilterModel.catch(() => ({})),
  query: FilterQueryModel.catch(() => []),
  hiddenColumns: HiddenColumnsModel,
})

export type ProceduresWidget = z.infer<typeof ProceduresWidgetModel>
export const ProceduresWidgetModel = BaseWidgetModel.extend({
  type: z.literal('procedures'),
  name: z.string().catch('Procedures'),
  procedureAddress: AddressModel.nullish(),
  /** Narrows the list to actions or to queries, unset for both. */
  procedureType: ProcedureTypeModel.nullish(),
  procedureName: z.string().nullish(),
})

export type ChartWidgetDisplay = z.infer<typeof ChartWidgetDisplayModel>
export const ChartWidgetDisplayModel = z.enum(['line', 'scatter', 'bar'])

export type ChartWidgetFit = z.infer<typeof ChartWidgetFitModel>
/** Which series bound the Y axis, the ones switched on in the legend or every one of them. */
export const ChartWidgetFitModel = z.enum(['shown', 'all'])

/** The most decimal places a widget reads a value out to, trailing zeros never shown.

Two places by default, enough to separate readings a sensor genuinely distinguishes without
carrying the noise of a float's last digits onto the screen.
*/
export const DecimalsModel = z.number().int().min(0).max(10).catch(2)

export type ChartWidgetSeries = z.infer<typeof ChartWidgetSeriesModel>
export const ChartWidgetSeriesModel = z.object({
  id: z.string().catch(() => v7()),
  field: z.string().nullish(),
  label: z.string().nullish(),
  /** The line's color as `#rrggbb`, written when the series is added and editable after. */
  color: z.string().nullish(),
})

export type ChartWidgetParticle = z.infer<typeof ChartWidgetParticleModel>
export const ChartWidgetParticleModel = z.object({
  address: AddressSelectorModel.nullish(),
  type: z.string().nullish(),
  /** Narrows the group to one connection's particles, unset for every connection's. */
  connection: z.string().nullish(),
  series: safeArrayOf(ChartWidgetSeriesModel),
})

export type ChartWidget = z.infer<typeof ChartWidgetModel>
export const ChartWidgetModel = BaseWidgetModel.extend({
  type: z.literal('chart'),
  name: z.string().catch('Chart'),
  display: ChartWidgetDisplayModel.catch('line'),
  fit: ChartWidgetFitModel.catch('shown'),
  /** Extend the Y axis to include zero, whatever the plotted extent. */
  fromZero: z.boolean().catch(false),
  decimals: DecimalsModel,
  /** Draw the Y axis positive-down, the convention for depth-like series. */
  flipY: z.boolean().catch(false),
  unit: z.string().nullish(),
  after: DateTimeModel.nullish(),
  timespan: z
    .union([z.number(), z.string()])
    .nullish()
    .catch(60 * 60),
  particles: safeArrayOf(ChartWidgetParticleModel),
})

export type TextWeight = z.infer<typeof TextWeightModel>
export const TextWeightModel = z.enum(['slim', 'normal', 'bold'])

export type MeterWidget = z.infer<typeof MeterWidgetModel>
export const MeterWidgetModel = BaseWidgetModel.extend({
  type: z.literal('meter'),
  name: z.string().catch('Meter'),
  particleAddress: AddressSelectorModel.nullish(),
  particleType: z.string().nullish(),
  particleField: z.string().nullish(),
  /** Narrows the reading to one connection's particles, unset for every connection's. */
  particleConnection: z.string().nullish(),
  decimals: DecimalsModel,
  fontSize: z.number().min(1).max(60).nullish(),
  fontWeight: TextWeightModel.default('normal').catch('normal'),
  prefix: z.string().nullish(),
  suffix: z.string().nullish(),
})

export type VideoWidget = z.infer<typeof VideoWidgetModel>
export const VideoWidgetModel = BaseWidgetModel.extend({
  type: z.literal('video'),
  name: z.string().catch('Video'),
  query: z.string().nullish(),
  autoplay: z.boolean().default(true).catch(true),
  startMuted: z.boolean().default(true).catch(true),
  showControls: z.boolean().default(true).catch(true),
})

/** A stored control color, in the vocabulary the old console wrote and the engine still holds. */
export type Color = z.infer<typeof ColorModel>
export const ColorModel = z.enum(['primary', 'positive', 'warning', 'negative'])

export type ButtonStyling = z.infer<typeof ButtonStylingModel>
export const ButtonStylingModel = z.enum(['flat', 'outlined'])

/** One action a button widget offers, and how pressing it behaves. */
export type ButtonAction = z.infer<typeof ButtonActionModel>
export const ButtonActionModel = z.object({
  id: z.string().catch(() => v7()),
  label: z.string().nullish(),
  address: AddressModel.nullish(),
  action: z.string().nullish(),
  arguments: z.record(z.string(), z.any()).catch(() => ({})),
  color: ColorModel.nullish().catch(undefined),
  styling: ButtonStylingModel.nullish().catch(undefined),
  tooltip: z.string().nullish().catch(undefined),

  // Locked, pressing the button runs it with its stored arguments. Unlocked, pressing asks for
  // the action's arguments first, which is one more look before anything runs, so a fresh
  // button starts unlocked.
  locked: z.boolean().catch(false),

  /** Whether running the action asks first. On by default because a workspace button is easy
  to press by accident. */
  confirm: z.boolean().catch(true),
})

/** Controls offered side by side, laid out as a bar. Buttons are the one kind it holds so far. */
export type ControlsWidget = BaseWidget & {
  type: 'controls'
  buttons: ButtonAction[]
}

export const ControlsWidgetModel = BaseWidgetModel.extend({
  type: z.literal('controls'),
  name: z.string().catch('Controls'),
  buttons: safeArrayOf(ButtonActionModel),
})

/** A controls widget in its legacy stored form, the single-action `button` widget.

The single-action fields are declared here rather than on `ControlsWidget` so the rest of the
app reaches an action only through `buttons`.
*/
type StoredButtonWidget = Omit<ControlsWidget, 'type'> & { type: 'button' } & Partial<
    Omit<ButtonAction, 'id' | 'locked' | 'confirm'>
  >

const StoredButtonWidgetModel = ControlsWidgetModel.extend({
  type: z.literal('button'),

  // The legacy single-action fields. Kept so a stored workspace still parses, and folded into
  // `buttons` by `upgradedWidget` on load.
  label: z.string().nullish(),
  address: AddressModel.nullish(),
  action: z.string().nullish(),
  arguments: z.record(z.string(), z.any()).nullish(),
  color: ColorModel.nullish().catch(undefined),
  styling: ButtonStylingModel.nullish().catch(undefined),
  tooltip: z.string().nullish().catch(undefined),
})

/** A named layout, as held by a carousel slide or a tab.

Written out rather than inferred because the types are mutually recursive.
*/
export type WidgetPage = {
  id: string
  name: string
  layout: WidgetRow[]
}

export const WidgetPageModel = z.object({
  id: z.string().catch(() => v7()),
  name: z.string().catch(''),
  get layout() {
    return safeArrayOf(WidgetRowModel)
  },
}) as unknown as z.ZodType<WidgetPage>

/** What a carousel calls its pages. */
export type CarouselSlide = WidgetPage

/** How a layout distributes height its rows have not claimed.

`last` gives it to the final row, `first` to the leading one, `even` shares it out, and `none`
leaves the rows at their dragged heights.
*/
export type LayoutExpand = z.infer<typeof LayoutExpandModel>
export const LayoutExpandModel = z.enum(['last', 'first', 'even', 'none'])

export type CarouselWidget = BaseWidget & {
  type: 'carousel'
  slides: WidgetPage[]

  /** How long each slide is shown, in seconds. */
  interval: number

  /** Whether it advances by itself instead of being stepped through by hand. */
  autoplay: boolean

  /** What the slides do with the height left over once their rows have taken theirs. */
  expand: LayoutExpand

  /** Whether rows may also be squeezed below their own heights to fit the slide. */
  shrink: boolean
}

export const CarouselWidgetModel = BaseWidgetModel.extend({
  type: z.literal('carousel'),
  name: z.string().catch('Carousel'),
  slides: safeArrayOf(WidgetPageModel),
  interval: z.number().min(1).max(3600).catch(15),
  // Off by default so a freshly added carousel does not start moving before it is set up.
  autoplay: z.boolean().catch(false),
  // The bottom of a slide is where empty space shows so the bottom row is given it.
  expand: LayoutExpandModel.catch('last'),
  // Off by default, squeezing rows below their dragged heights is opt-in.
  shrink: z.boolean().catch(false),
})

/** Pages shown one at a time, reached by name rather than in turn. */
export type TabsWidget = BaseWidget & {
  type: 'tabs'
  tabs: WidgetPage[]
  fill: boolean

  /** What the tabs do with the height left over once their rows have taken theirs. */
  expand: LayoutExpand

  /** Whether rows may also be squeezed below their own heights to fit the tab. */
  shrink: boolean
}

export const TabsWidgetModel = BaseWidgetModel.extend({
  type: z.literal('tabs'),
  name: z.string().catch('Tabs'),
  tabs: safeArrayOf(WidgetPageModel),

  // Whether the tabs share the strip's width evenly rather than each taking only the room its
  // own name needs.
  fill: z.boolean().catch(false),
  // The bottom of a tab is where empty space shows so the bottom row is given it.
  expand: LayoutExpandModel.catch('last'),
  // Off by default, squeezing rows below their dragged heights is opt-in.
  shrink: z.boolean().catch(false),
})

export type Widget =
  | MessagesWidget
  | ParticlesWidget
  | AlertsWidget
  | LogsWidget
  | ProceduresWidget
  | ChartWidget
  | MeterWidget
  | VideoWidget
  | ControlsWidget
  | CarouselWidget
  | TabsWidget

export type WidgetType = Widget['type']

/** A widget of a kind this console has no model for.

Its fields ride along unparsed so the next save does not delete a widget another console
version stored, and this console draws a placeholder for it.
*/
export const UnknownWidgetModel = z.looseObject({
  ...BaseWidgetModel.shape,
  type: z.string(),
  name: z.string().catch(''),
})

/** The stored model for each widget kind, which is where its field defaults live. */
export const widgetModels = {
  messages: MessagesWidgetModel,
  particles: ParticlesWidgetModel,
  alerts: AlertsWidgetModel,
  logs: LogsWidgetModel,
  procedures: ProceduresWidgetModel,
  chart: ChartWidgetModel,
  meter: MeterWidgetModel,
  video: VideoWidgetModel,
  controls: ControlsWidgetModel,
  carousel: CarouselWidgetModel,
  tabs: TabsWidgetModel,
} as const

/** Kinds that were renamed without changing shape, rewritten on the stored data before its
model parses. A kind whose shape also changed migrates in `upgradedWidget` instead. */
const renamedWidgetTypes: Record<string, WidgetType> = {
  value: 'meter',
}

function migratedRawWidget(stored: unknown): unknown {
  if (typeof stored !== 'object' || stored == null) {
    return stored
  }

  const renamed = renamedWidgetTypes[(stored as { type?: string }).type ?? '']

  return renamed == null ? stored : { ...stored, type: renamed }
}

export const WidgetModel = z.preprocess(
  migratedRawWidget,
  z
    .discriminatedUnion('type', [
      MessagesWidgetModel,
      ParticlesWidgetModel,
      AlertsWidgetModel,
      LogsWidgetModel,
      ProceduresWidgetModel,
      ChartWidgetModel,
      MeterWidgetModel,
      VideoWidgetModel,
      ControlsWidgetModel,
      // The controls widget's legacy stored kind, turned into `controls` by `upgradedWidget` on
      // load.
      StoredButtonWidgetModel,
      CarouselWidgetModel,
      TabsWidgetModel,
    ])
    .or(UnknownWidgetModel),
) as unknown as z.ZodType<Widget>

export const widgetWidthSubdivisions = 120

/** Written out rather than inferred for the same reason as `WidgetPage`, the types are
mutually recursive. */
export type WidgetRow = {
  id: string
  height: number
  collapsed: boolean
  widgets: Widget[]
}

export const WidgetRowModel = z.object({
  id: z.string().catch(() => v7()),
  height: z.number().catch(250),
  collapsed: z.boolean().catch(false),
  widgets: safeArrayOf(WidgetModel),
}) as unknown as z.ZodType<WidgetRow>

/** The pages a widget holds, or none.

Everything that walks a workspace's layouts goes through here so a new pages-holding widget kind
only needs to be named here.
*/
export function pagesOf(widget: Widget): WidgetPage[] {
  if (widget.type === 'carousel') {
    return widget.slides
  }
  if (widget.type === 'tabs') {
    return widget.tabs
  }

  return []
}

/** A copy of `widget` holding `pages` in place of the ones it held. */
export function withPages(widget: Widget, pages: WidgetPage[]): Widget {
  if (widget.type === 'carousel') {
    return { ...widget, slides: pages }
  }
  if (widget.type === 'tabs') {
    return { ...widget, tabs: pages }
  }

  return widget
}

/** Return `widget` in its current shape, upgrading the legacy `button` kind and its inline
action fields to a `controls` widget. */
function upgradedWidget(widget: Widget): Widget {
  const pages = pagesOf(widget).map((page) => ({
    ...page,
    layout: upgradedRows(page.layout),
  }))

  // A carousel or a tab strip always holds at least one page since one with no pages has no
  // layout to drag or paste widgets into.
  const upgraded = withPages(
    widget,
    pages.length === 0 && (widget.type === 'carousel' || widget.type === 'tabs')
      ? [{ id: v7(), name: '', layout: [] }]
      : pages,
  )

  const stored = upgraded as Widget | StoredButtonWidget
  if (stored.type !== 'button') {
    return upgraded
  }

  const { label, address, action, color, styling, tooltip, arguments: values, ...rest } = stored
  const held = { label, address, action, color, styling, tooltip }

  // Stored button widgets carry empty arguments either way so the settable fields decide
  // whether there is a configured button to carry over.
  const wasConfigured = Object.values(held).some((value) => value != null)
  if (stored.buttons.length > 0 || !wasConfigured) {
    return { ...rest, type: 'controls', buttons: stored.buttons }
  }

  return {
    ...rest,
    type: 'controls',
    buttons: [ButtonActionModel.parse({ ...held, arguments: values ?? {} })],
  }
}

function upgradedRows(rows: WidgetRow[]): WidgetRow[] {
  return rows.map((row) => ({ ...row, widgets: row.widgets.map(upgradedWidget) }))
}

/** Widgets on the system clipboard, keeping their row structure.

The `ceres` marker tells a widget paste apart from any other text.
*/
export type WidgetClipboard = z.infer<typeof WidgetClipboardModel>
export const WidgetClipboardModel = z.object({
  ceres: z.literal('widgets'),
  // Upgraded on the way in because a copy can carry a legacy widget shape.
  rows: safeArrayOf(WidgetRowModel).transform(upgradedRows),
})

export type WorkspaceMeta = z.infer<typeof WorkspaceMetaModel>

/** Presentation state the console keeps alongside a workspace's contents.

The engine stores this without interpreting it so nothing here may affect how a workspace
behaves, only how the console chooses to display it.
*/
export const WorkspaceMetaModel = z.object({
  // Position among the workspaces scoped to the same component, ascending. Workspaces without
  // one sort last, which is where a newly created workspace belongs.
  order: z.number().nullish().catch(undefined),
})

export type WorkspaceDataInput = z.input<typeof WorkspaceDataModel>
export type WorkspaceData = z.infer<typeof WorkspaceDataModel>
export const WorkspaceDataModel = z.object({
  layout: (WidgetRowModel as z.ZodType<WidgetRow>)
    .array()
    .catch(() => [])
    .transform(upgradedRows),
  meta: WorkspaceMetaModel.catch(() => ({ order: undefined })),
})

/** Whether a caller may rename, delete, or otherwise write this workspace.

A private workspace belongs to its owner alone so they may write it whatever their access on the
placement. A shared one follows the placement.
*/
export function isWorkspaceWritable(
  workspace: Workspace,
  userId: string | null | undefined,
  canManagePlacement: boolean,
): boolean {
  if (workspace.owner_id != null) {
    return workspace.owner_id === userId
  }

  return canManagePlacement
}

/** Sort workspaces into the shared standard order.

Position is carried in each workspace's own data, and those without one sort last, which is where a
newly created workspace belongs. Ties fall back to the ID, which is creation order, so renaming a
workspace never moves it.
*/
export function inStandardOrder(workspaces: Workspace[]): Workspace[] {
  return orderBy(workspaces, [
    (workspace) => workspace.data.meta.order ?? Number.MAX_SAFE_INTEGER,
    (workspace) => workspace.id,
  ])
}

/** Return a workspace's data without `meta`.

`meta` is rewritten by any manager reordering a strip so including it in edit comparisons would
mark every workspace in the strip as edited.
*/
export function withoutMeta(data: WorkspaceData): Omit<WorkspaceData, 'meta'> {
  // Content is named rather than spread so adding a field to a workspace's data fails to compile
  // here until it is decided whether that field is content or presentation.
  const { layout } = data
  return { layout }
}

/** Strip every chart series `id` from `rows`, recursing into carousel and tab pages.

`ChartWidgetSeriesModel.id` mints a fresh ID on every parse of a series stored without one, so an
ID-less legacy series never compares equal to itself across parses. Comparisons that only care
about content go through this first.
*/
function withoutChartSeriesIds(rows: WidgetRow[]): WidgetRow[] {
  return rows.map((row) => ({
    ...row,
    widgets: row.widgets.map((widget) => {
      const pages = pagesOf(widget)
      const scrubbed =
        pages.length === 0
          ? widget
          : withPages(
              widget,
              pages.map((page) => ({ ...page, layout: withoutChartSeriesIds(page.layout) })),
            )

      if (scrubbed.type !== 'chart') {
        return scrubbed
      }

      return {
        ...scrubbed,
        // The cast restores the series element type, which `omit` narrows to a `Pick`. The
        // result is only ever compared, never stored.
        particles: scrubbed.particles.map((particle) => ({
          ...particle,
          series: particle.series.map((series) => omit(series, 'id') as ChartWidgetSeries),
        })),
      }
    }),
  }))
}

/** Workspace data comparable across parses, with presentation `meta` and minted chart series IDs
removed.

Use for any comparison that should treat two parses of the same content as equal: the `edited`
check, edit reconciliation, and the tab strip's unsaved-edit indicator.
*/
export function comparableWorkspaceData(data: WorkspaceData): Omit<WorkspaceData, 'meta'> {
  return { layout: withoutChartSeriesIds(withoutMeta(data).layout) }
}

export type Workspace = z.infer<typeof WorkspaceModel>

/** What a workspace write accepts. Declared with every caught field optional, because zod 4's
input type keeps `.catch()` fields required. */
export type WorkspaceInput = Partial<z.input<typeof WorkspaceModel>> & { name: string }

export const WorkspaceModel = z.object({
  id: z.string().catch(() => v7()),
  name: z.string(),
  scope: AddressModel.catch(() => Address.parse(engineRoot)),
  owner_id: z.string().nullish().catch(null),
  show_when_logged_out: z.boolean().catch(false),
  data: WorkspaceDataModel.catch(() => WorkspaceDataModel.parse({})),
})

export type WorkspaceEdit = z.infer<typeof WorkspaceEditModel>
export const WorkspaceEditModel = z.object({
  user_id: z.string(),
  workspace_id: z.string(),
  data: WorkspaceDataModel,
})

/** The one component a widget is pointed at, or null when it is pointed at none.

A widget pointed at several components returns none since the shortcut is for a view of
one thing.
*/
export function widgetTargetSelector(widget: Widget) {
  if (widget.restricted) {
    return null
  }

  switch (widget.type) {
    case 'procedures':
      return widget.procedureAddress ?? null
    case 'meter':
      return widget.particleAddress ?? null
    default:
      return null
  }
}

// A value that changes whenever any of a widget's address-bearing fields change. Used to clear a
// restricted stub's lock placeholder when the user repoints it.
export function widgetTargetSignature(widget: Widget): string {
  const values: unknown[] = []

  if ('address' in widget) {
    values.push(widget.address)
  }
  if ('commandAddress' in widget) {
    values.push(widget.commandAddress)
  }
  if ('procedureAddress' in widget) {
    values.push(widget.procedureAddress)
  }
  if ('particleAddress' in widget) {
    values.push(widget.particleAddress)
  }
  if ('query' in widget) {
    values.push(widget.query)
  }
  if ('filter' in widget) {
    // Guarded since an unknown kind can carry a `filter` of any shape at all.
    values.push((widget.filter as { address?: unknown } | null)?.address)
  }
  if ('particles' in widget) {
    values.push(widget.particles.map((particle) => particle.address?.toString() ?? null))
  }
  if ('buttons' in widget) {
    values.push(widget.buttons.map((button) => button.address?.toString() ?? null))
  }

  return JSON.stringify(values.map((value) => value?.toString() ?? null))
}
