import { escape } from 'lodash-es'

/** Markup that `html` built or `trusted` vouched for, which interpolating keeps as it is. */
export class SafeHtml {
  constructor(readonly text: string) {}

  toString(): string {
    return this.text
  }
}

/** Markup a library produced, such as a chart's legend marker, taken as it is. */
export function trusted(markup: string): SafeHtml {
  return new SafeHtml(markup)
}

function rendered(value: unknown): string {
  if (value instanceof SafeHtml) {
    return value.text
  }

  if (Array.isArray(value)) {
    return value.map(rendered).join('')
  }

  return escape(value == null ? '' : String(value))
}

/** Markup from a template, escaping every interpolated value except other markup. An array
interpolates as its items joined. */
export function html(strings: TemplateStringsArray, ...values: unknown[]): SafeHtml {
  return new SafeHtml(
    strings.reduce(
      (markup, string, index) =>
        markup + string + (index < values.length ? rendered(values[index]) : ''),
      '',
    ),
  )
}
