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
  microsecond: number
  /** ISO weekday, 1 for Monday. */
  weekday: number
  doy: number
  /** Whole seconds since the Unix epoch. */
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

function readTime(when: Date | string, zone: string): PathTemplateTime {
  const instant = typeof when === 'string' ? new Date(when) : when
  // A `Date` holds milliseconds, so an ISO string's own fraction carries the microseconds.
  const fraction = typeof when === 'string' ? /T[^.]*\.(\d+)/.exec(when)?.[1] : undefined
  const microsecond =
    fraction == null
      ? (((instant.getTime() % 1000) + 1000) % 1000) * 1000
      : Number(fraction.padEnd(6, '0').slice(0, 6))

  const parts = zoneFormatter(zone).formatToParts(instant)
  const [year, month, day, hour, minute, second] = (
    ['year', 'month', 'day', 'hour', 'minute', 'second'] as const
  ).map((type) => Number(part(parts, type)))
  const offsetMatch = /([+-])(\d{2}):(\d{2})/.exec(part(parts, 'timeZoneName'))
  const offset =
    offsetMatch == null
      ? 0
      : (offsetMatch[1] === '-' ? -1 : 1) * (Number(offsetMatch[2]) * 60 + Number(offsetMatch[3]))

  const date = Date.UTC(year!, month! - 1, day)
  return {
    year: year!,
    month: month!,
    day: day!,
    hour: hour!,
    minute: minute!,
    second: second!,
    microsecond,
    weekday: ((new Date(date).getUTCDay() + 6) % 7) + 1,
    doy: (date - Date.UTC(year!, 0, 1)) / DAY + 1,
    epoch: Math.floor(instant.getTime() / 1000),
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

function hour12(time: PathTemplateTime) {
  return ((time.hour + 11) % 12) + 1
}

type PathTemplateRender = (time: PathTemplateTime) => string

// The Unicode LDML date symbols (UTS #35) a template may use, the same set `ceres.paths` renders.
const SYMBOLS: Readonly<Record<string, PathTemplateRender>> = {
  yyyy: (time) => pad(time.year, 4),
  yy: (time) => pad(time.year % 100),
  MM: (time) => pad(time.month),
  M: (time) => String(time.month),
  MMM: (time) => MONTHS[time.month - 1]!.slice(0, 3),
  MMMM: (time) => MONTHS[time.month - 1]!,
  dd: (time) => pad(time.day),
  d: (time) => String(time.day),
  DDD: (time) => pad(time.doy, 3),
  HH: (time) => pad(time.hour),
  H: (time) => String(time.hour),
  hh: (time) => pad(hour12(time)),
  h: (time) => String(hour12(time)),
  a: (time) => (time.hour < 12 ? 'AM' : 'PM'),
  mm: (time) => pad(time.minute),
  ss: (time) => pad(time.second),
  ...Object.fromEntries(
    [1, 2, 3, 4, 5, 6].map((width) => [
      'S'.repeat(width),
      (time: PathTemplateTime) => pad(time.microsecond, 6).slice(0, width),
    ]),
  ),
  EEE: (time) => WEEKDAYS[time.weekday - 1]!.slice(0, 3),
  EEEE: (time) => WEEKDAYS[time.weekday - 1]!,
  Z: (time) => formatOffset(time.offset),
  XX: (time) => (time.offset === 0 ? 'Z' : formatOffset(time.offset)),
}

const EPOCH_ATOMS: ReadonlyMap<string, bigint> = new Map([
  ['epoch', 1n],
  ['epoch:ms', 1_000n],
  ['epoch:us', 1_000_000n],
])

const HOURS = new Set(['HH', 'H', 'hh', 'h'])

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
    for (const name of [...declared].sort()) {
      if (Object.hasOwn(SYMBOLS, name) || IDENTITY_ATOMS.has(name) || name === 'epoch') {
        throw new Error(`atom '${name}' is a built-in`)
      }
    }

    const parts: (string | PathTemplateAtom)[] = []
    let position = 0
    for (const match of source.matchAll(/\{\{|\}\}|\{([^{}]*)\}|[{}]/g)) {
      parts.push(source.slice(position, match.index))
      position = match.index + match[0].length
      if (match[0] === '{{' || match[0] === '}}') {
        parts.push(match[0][0]!)
      } else if (match[1] == null) {
        throw new Error(`template '${source}' has an unmatched brace`)
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

    checkClock(source, this.atoms)
    this.render(PROBE, 'UTC', Object.fromEntries([...this.atoms].map((name) => [name, 'x'])))
  }

  /**
   * Render the path for `when` in the IANA time zone `zone`, a `/` between segments. An ISO
   * string keeps the microseconds a `Date` drops.
   *
   * @throws {Error} If a name atom has no value in `values` or renders a separator, or the path
   *   breaks a rule the constructor checks.
   */
  render(when: Date | string, zone = 'UTC', values: Readonly<Record<string, string>> = {}) {
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
  if (colon >= 0 || name === 'epoch') {
    const perSecond = EPOCH_ATOMS.get(body)
    if (perSecond == null) {
      throw new Error(
        `template '${source}' uses '{${body}}', only '{epoch}' takes a unit, ms or us`,
      )
    }

    // Integer arithmetic, since a microsecond count passes what a float holds exactly.
    return {
      name: body,
      render: (time) =>
        String(
          BigInt(time.epoch) * perSecond + (BigInt(time.microsecond) * perSecond) / 1_000_000n,
        ),
    }
  }

  const symbol = SYMBOLS[name]
  if (symbol != null) {
    return { name, render: (time) => symbol(time) }
  }

  if (IDENTITY_ATOMS.has(name) || extras.has(name)) {
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

  if (/^([A-Za-z])\1*$/.test(name)) {
    throw new Error(`template '${source}' uses '{${name}}', a symbol a template does not render`)
  }

  throw new Error(`template '${source}' uses '{${name}}', which is not an atom`)
}

function checkClock(source: string, atoms: ReadonlySet<string>) {
  if ((atoms.has('hh') || atoms.has('h')) && !atoms.has('a')) {
    throw new Error(`template '${source}' uses the 12-hour clock without '{a}'`)
  }

  if (atoms.has('mm') && ![...HOURS].some((hour) => atoms.has(hour))) {
    throw new Error(`template '${source}' uses '{mm}' without an hour`)
  }

  if (atoms.has('ss') && !atoms.has('mm')) {
    throw new Error(`template '${source}' uses '{ss}' without '{mm}'`)
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
