/**
 * The path templates of `ceres.paths`, rendered in the browser so the console can open a mount's
 * current dated folder. `tests/vectors/path-template.json` holds both renderers to one result.
 */

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const

const WEEKDAYS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
] as const

const DAY = 86_400_000

/** The parts of one instant read in one time zone. */
interface PathTemplateTime {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
  /** ISO weekday, 1 for Monday. */
  weekday: number
  doy: number
  isoYear: number
  isoWeek: number
  epoch: number
  /** Offset from UTC in minutes. */
  offset: number
}

// One formatter per time zone a mount names, a handful in any project.
const formatters = new Map<string, Intl.DateTimeFormat>()

function zoneFormatter(zone: string) {
  let formatter = formatters.get(zone)
  if (formatter == null) {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      timeZoneName: 'longOffset',
    })
    formatters.set(zone, formatter)
  }

  return formatter
}

function part(parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes) {
  return parts.find((candidate) => candidate.type === type)?.value ?? ''
}

function readTime(when: Date, zone: string): PathTemplateTime {
  const parts = zoneFormatter(zone).formatToParts(when)
  const [year, month, day, hour, minute, second] = (
    ['year', 'month', 'day', 'hour', 'minute', 'second'] as const
  ).map((type) => Number(part(parts, type)))
  const offsetMatch = /([+-])(\d{2}):(\d{2})/.exec(part(parts, 'timeZoneName'))
  const offset =
    offsetMatch == null
      ? 0
      : (offsetMatch[1] === '-' ? -1 : 1) * (Number(offsetMatch[2]) * 60 + Number(offsetMatch[3]))

  const date = Date.UTC(year!, month! - 1, day)
  const weekday = ((new Date(date).getUTCDay() + 6) % 7) + 1
  const thursday = new Date(date + (4 - weekday) * DAY)
  const isoYear = thursday.getUTCFullYear()
  return {
    year: year!,
    month: month!,
    day: day!,
    hour: hour!,
    minute: minute!,
    second: second!,
    weekday,
    doy: (date - Date.UTC(year!, 0, 1)) / DAY + 1,
    isoYear,
    isoWeek: Math.floor((thursday.getTime() - Date.UTC(isoYear, 0, 1)) / DAY / 7) + 1,
    epoch: Math.floor(when.getTime() / 1000),
    offset,
  }
}

function pad(value: number, width = 2) {
  return String(value).padStart(width, '0')
}

function formatOffset(minutes: number) {
  const sign = minutes < 0 ? '-' : '+'
  return `${sign}${pad(Math.floor(Math.abs(minutes) / 60))}${pad(Math.abs(minutes) % 60)}`
}

type PathTemplateRender = (time: PathTemplateTime) => string

// The `strftime` directives a `{time:...}` atom may use, the same set `ceres.paths` renders.
const DIRECTIVES: Readonly<Record<string, PathTemplateRender>> = {
  Y: (time) => pad(time.year, 4),
  y: (time) => pad(time.year % 100),
  m: (time) => pad(time.month),
  d: (time) => pad(time.day),
  H: (time) => pad(time.hour),
  I: (time) => pad(((time.hour + 11) % 12) + 1),
  p: (time) => (time.hour < 12 ? 'AM' : 'PM'),
  M: (time) => pad(time.minute),
  S: (time) => pad(time.second),
  j: (time) => pad(time.doy, 3),
  b: (time) => MONTHS[time.month - 1]!.slice(0, 3),
  B: (time) => MONTHS[time.month - 1]!,
  a: (time) => WEEKDAYS[time.weekday - 1]!.slice(0, 3),
  A: (time) => WEEKDAYS[time.weekday - 1]!,
  G: (time) => pad(time.isoYear, 4),
  V: (time) => pad(time.isoWeek),
  u: (time) => String(time.weekday),
  w: (time) => String(time.weekday % 7),
  z: (time) => formatOffset(time.offset),
  // Zone abbreviations differ between tzdata releases and are missing for most of the world, so a
  // zone renders as its offset, as `ceres.paths` renders it.
  Z: (time) => (time.offset === 0 ? 'UTC' : formatOffset(time.offset)),
  '%': () => '%',
}

function strftime(pattern: string): PathTemplateRender {
  const pieces: (string | PathTemplateRender)[] = []
  for (const match of pattern.matchAll(/%([\s\S]?)|[^%]+/g)) {
    if (!match[0].startsWith('%')) {
      pieces.push(match[0])
      continue
    }

    const directive = DIRECTIVES[match[1]!]
    if (directive == null) {
      throw new Error(`'${pattern}' uses '${match[0]}', which a template cannot use`)
    }

    pieces.push(directive)
  }

  return (time) => pieces.map((piece) => (typeof piece === 'string' ? piece : piece(time))).join('')
}

const TIME_ATOMS: Readonly<Record<string, PathTemplateRender>> = {
  year: strftime('%Y'),
  month: strftime('%m'),
  day: strftime('%d'),
  hour: strftime('%H'),
  minute: strftime('%M'),
  second: strftime('%S'),
  date: strftime('%Y%m%d'),
  time: strftime('%H%M%S'),
  datetime: strftime('%Y%m%dT%H%M%S'),
  week: strftime('%V'),
  doy: strftime('%j'),
  epoch: (time) => String(time.epoch),
  zone: strftime('%Z'),
  yy: strftime('%y'),
  m: (time) => String(time.month),
  d: (time) => String(time.day),
  h: (time) => String(time.hour),
  mon: strftime('%b'),
  month_name: strftime('%B'),
  wd: strftime('%a'),
  weekday: strftime('%A'),
}

const IDENTITY_ATOMS = new Set(['component', 'mount', 'connection', 'project', 'host'])

// Device names Windows reserves in every directory, with or without an extension.
const RESERVED = new Set([
  'CON',
  'PRN',
  'AUX',
  'NUL',
  ...['COM', 'LPT'].flatMap((device) => Array.from({ length: 9 }, (_, i) => `${device}${i + 1}`)),
])

// eslint-disable-next-line no-control-regex
const FORBIDDEN = /[<>:"|?*\\\x00-\x1f]/

// Renders every template once at construction, so a pattern that can only fail at render time
// fails at once, the same probe `ceres.paths` uses.
const PROBE = new Date(Date.UTC(2001, 1, 3, 4, 5, 6))

interface PathTemplateAtom {
  name: string
  render: (time: PathTemplateTime, values: Readonly<Record<string, string>>) => string
}

/** A relative path rendered from a time and a few names, as `ceres.paths.PathTemplate` reads it. */
export class PathTemplate {
  readonly source: string
  readonly atoms: ReadonlySet<string>
  private readonly parts: readonly (string | PathTemplateAtom)[]

  /**
   * Parse `source`, which may also use the atoms named in `extras`.
   *
   * @throws {Error} If `source` breaks a rule `ceres.paths.PathTemplate` checks.
   */
  constructor(source: string, extras: Iterable<string> = []) {
    const declared = new Set(extras)
    const parts: (string | PathTemplateAtom)[] = []
    let position = 0
    for (const match of source.matchAll(/\{\{|\}\}|\{([^{}]*)\}|[{}]/g)) {
      parts.push(source.slice(position, match.index))
      position = match.index + match[0].length
      if (match[0] === '{{' || match[0] === '}}') {
        parts.push(match[0][0]!)
      } else if (match[1] == null) {
        throw new Error(`template '${source}' has an unmatched '${match[0]}'`)
      } else {
        parts.push(parseAtom(source, match[1], declared))
      }
    }

    parts.push(source.slice(position))
    this.source = source
    this.parts = parts.filter((piece) => piece !== '')
    this.atoms = new Set(
      this.parts.flatMap((piece) => (typeof piece === 'string' ? [] : [piece.name])),
    )

    if (source.startsWith('/') || source.startsWith('\\')) {
      throw new Error(`template '${source}' is absolute, a template renders relative paths`)
    }

    this.render(PROBE, 'UTC', Object.fromEntries([...this.atoms].map((name) => [name, 'x'])))
  }

  /**
   * Render the path for `when` in the IANA time zone `zone`, a `/` between segments.
   *
   * @throws {Error} If a name atom has no value in `values` or renders a separator, or the path
   *   breaks a rule the constructor checks.
   */
  render(when: Date, zone = 'UTC', values: Readonly<Record<string, string>> = {}) {
    const time = readTime(when, zone)
    const path = this.parts
      .map((piece) => {
        if (typeof piece === 'string') {
          return piece
        }

        const text = piece.render(time, values)
        if (text.includes('/') || text.includes('\\')) {
          throw new Error(`atom '{${piece.name}}' renders '${text}', which holds a separator`)
        }

        return text
      })
      .join('')
    for (const segment of path.split('/')) {
      checkSegment(this.source, segment)
    }

    return path
  }
}

function parseAtom(source: string, body: string, extras: ReadonlySet<string>): PathTemplateAtom {
  const colon = body.indexOf(':')
  const name = colon < 0 ? body : body.slice(0, colon)
  if (colon >= 0) {
    if (name !== 'time') {
      throw new Error(
        `template '${source}' gives a pattern to '{${name}}', only '{time}' takes one`,
      )
    }

    const render = strftime(body.slice(colon + 1))
    return { name, render: (time) => render(time) }
  }

  const time = TIME_ATOMS[name]
  if (time != null) {
    return { name, render: (moment) => time(moment) }
  }

  if (!IDENTITY_ATOMS.has(name) && !extras.has(name)) {
    throw new Error(`template '${source}' uses '{${name}}', which is not an atom`)
  }

  return {
    name,
    render: (_, values) => {
      const value = values[name]
      if (value == null) {
        throw new Error(`atom '{${name}}' has no value`)
      }

      return value
    },
  }
}

function checkSegment(source: string, segment: string) {
  if (segment === '' || segment === '.' || segment === '..') {
    throw new Error(`template '${source}' renders an empty, '.', or '..' segment`)
  }

  if (FORBIDDEN.test(segment)) {
    throw new Error(`template '${source}' renders '${segment}', which holds a reserved character`)
  }

  if (RESERVED.has(segment.split('.')[0]!.toUpperCase()) || /[. ]$/.test(segment)) {
    throw new Error(`template '${source}' renders '${segment}', a name Windows reserves`)
  }
}
