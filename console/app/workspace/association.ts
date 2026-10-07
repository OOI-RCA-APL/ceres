import type { WorkspaceData } from './models'

import { type Address, AddressSelector, engineRoot } from '@/api/address'

// Raw JSON rather than parsed widgets, so this walk reads the same fields the server's own
// `pin_widget_addresses` does and leaves everything else exactly as stored.
type Raw = Record<string, unknown>

const addressKeys = ['address', 'commandAddress', 'particleAddress', 'procedureAddress']
const pageKeys = ['slides', 'tabs']
const listKeys = ['buttons', 'particles']

function isRaw(value: unknown): value is Raw {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

/** Every widget in a raw layout, including those on carousel slides and tab pages. */
function* widgetsIn(layout: unknown): Generator<Raw> {
  if (!Array.isArray(layout)) {
    return
  }

  for (const row of layout) {
    const widgets = isRaw(row) ? row.widgets : null
    if (!Array.isArray(widgets)) {
      continue
    }

    for (const widget of widgets) {
      if (!isRaw(widget)) {
        continue
      }

      yield widget
      for (const key of pageKeys) {
        const pages = widget[key]
        if (Array.isArray(pages)) {
          for (const page of pages) {
            if (isRaw(page)) {
              yield* widgetsIn(page.layout)
            }
          }
        }
      }
    }
  }
}

function pin(value: unknown, scope: Address): unknown {
  if (typeof value !== 'string') {
    return value
  }

  if (value === '') {
    return scope.isEngine ? value : scope.toString()
  }

  // The server reads a bare `all` as `:all` before resolving it, which `asAbsolute` does not.
  const normalized = value
    .split('|')
    .map((segment) => (segment === 'all' ? ':all' : segment))
    .join('|')
  try {
    return AddressSelector.parse(normalized).asAbsolute(scope).toString()
  } catch {
    return value
  }
}

/** Every address value a raw widget holds, with the query's leading address standing for it. */
function addressValues(widget: Raw): unknown[] {
  const values: unknown[] = addressKeys.map((key) => widget[key])

  if (typeof widget.query === 'string' && widget.query.includes('::')) {
    values.push(widget.query.split('::', 1)[0])
  }
  if (isRaw(widget.filter)) {
    values.push(widget.filter.address)
  }
  for (const key of listKeys) {
    const entries = widget[key]
    if (Array.isArray(entries)) {
      values.push(...entries.filter(isRaw).map((entry) => entry.address))
    }
  }

  return values
}

function pinWidget(widget: Raw, scope: Address) {
  for (const key of addressKeys) {
    if (key in widget) {
      widget[key] = pin(widget[key], scope)
    }
  }

  if (typeof widget.query === 'string' && widget.query.includes('::')) {
    const at = widget.query.indexOf('::')
    widget.query = `${pin(widget.query.slice(0, at), scope) as string}${widget.query.slice(at)}`
  }
  if (isRaw(widget.filter) && 'address' in widget.filter) {
    widget.filter.address = pin(widget.filter.address, scope)
  }
  for (const key of listKeys) {
    const entries = widget[key]
    if (Array.isArray(entries)) {
      for (const entry of entries.filter(isRaw)) {
        if ('address' in entry) {
          entry.address = pin(entry.address, scope)
        }
      }
    }
  }
}

/** A copy of `data` as raw JSON, with every relative widget address resolved against `scope`.

Mirrors the server's `pin_widget_addresses`, which a change of placement runs on its own. A copy
made elsewhere is a new workspace, so it is pinned here before it is created. An unset address is
left unset, since it stands for whatever placement the workspace has.
*/
export function pinWidgetAddresses(data: WorkspaceData, scope: Address): Raw {
  const raw = JSON.parse(JSON.stringify(data)) as Raw
  for (const widget of widgetsIn(raw.layout)) {
    pinWidget(widget, scope)
  }

  return raw
}

/** How many widgets of pinned `data` name a component outside `placement`.

A workspace on a component reaches only that component and those beneath it, so these widgets would
show nothing there. The engine root reaches everything.
*/
export function widgetsOutside(data: Raw, placement: string): number {
  if (placement === engineRoot) {
    return 0
  }

  let count = 0
  for (const widget of widgetsIn(data.layout)) {
    const outside = addressValues(widget).some(
      (value) =>
        typeof value === 'string' &&
        value.split('|').some((segment) => {
          const base = segment.split(':', 1)[0] ?? ''
          return (
            base.startsWith('@') &&
            base !== '@' &&
            base !== placement &&
            !base.startsWith(`${placement}.`)
          )
        }),
    )
    if (outside) {
      count++
    }
  }

  return count
}
