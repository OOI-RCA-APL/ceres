import * as z from 'zod'

/** The address of the engine root, the placement of anything not bound to a component. */
export const engineRoot = '~'

const name = '[a-zA-Z_-][a-zA-Z0-9_-]*'
const modifier = ':(all|children|descendants)'
const base = `@?${name}(\\.${name})*`
const segment = `\\~(:(all|descendants))?|${base}(${modifier})?|@${modifier}|${modifier}`

const addressSelectorRegex = new RegExp(`^(?:${segment})(?:\\|(?:${segment}))*$`)
const addressRegex = new RegExp(`^(?:~|@?${name}(\\.${name})*)$`)

export class AddressSelector {
  public readonly value: string

  constructor(value: string | AddressSelector) {
    if (typeof value !== 'string' && !(value instanceof AddressSelector)) {
      throw new Error(`invalid address selector: ${value}`)
    }

    value = value.toString().trim()
    if (!addressSelectorRegex.test(value)) {
      throw new Error(`invalid address selector: ${value}`)
    }

    this.value = value
  }

  public static parse(address: string | AddressSelector): AddressSelector {
    return new AddressSelector(address)
  }

  public valueOf(): string {
    return this.value
  }

  public toJSON(): string {
    return this.value
  }

  public toString(): string {
    return this.value
  }

  public equals(other: string | Address): boolean {
    return other.valueOf() === this.value
  }

  public get isAbsolute(): boolean {
    return this.value === '~' || this.value.startsWith('@') || this.value.startsWith(':')
  }

  // Resolve relative segments against a root address, mirroring the backend `as_absolute`.
  public asAbsolute(root: Address | null): AddressSelector {
    const base = root == null || root.value === '~' ? '@' : root.value
    const segments = this.value.split('|').map((segment) => {
      if (segment.startsWith(':')) {
        return base + segment
      } else if (segment.startsWith('~') || segment.startsWith('@')) {
        return segment
      } else if (base === '@') {
        return base + segment
      } else if (segment === '') {
        return base
      } else {
        return `${base}.${segment}`
      }
    })
    return new AddressSelector(segments.join('|'))
  }

  /** Whether this selector picks out an address, mirroring the backend `matches`.
   *
   * Each segment is read as written, so a selector that may be relative is resolved through
   * `asAbsolute` first.
   */
  public selects(address: string | Address): boolean {
    const value = address.toString()
    return this.value.split('|').some((segment) => segmentSelects(segment, value))
  }
}

/** Whether one absolute segment picks out an address, mirroring the backend's own. */
function segmentSelects(segment: string, address: string): boolean {
  const marker = segment.indexOf(':')
  if (marker < 0) {
    return address === segment
  }

  const base = segment.slice(0, marker)
  const modifier = segment.slice(marker + 1)
  if (base === engineRoot) {
    // The engine has no children form, so only these two arise.
    return modifier === 'all' || address !== engineRoot
  }

  if (base === '@') {
    // With no component named, `all` and `descendants` both reach every component, and
    // `children` the top-level ones.
    return modifier === 'children'
      ? address.startsWith('@') && !address.includes('.')
      : address !== engineRoot
  }

  const descendant = address.startsWith(`${base}.`) ? address.slice(base.length + 1) : null
  switch (modifier) {
    case 'all':
      return address === base || descendant != null
    case 'descendants':
      return descendant != null
    default:
      return descendant != null && !descendant.includes('.')
  }
}

export class Address extends AddressSelector {
  constructor(value: string | AddressSelector) {
    super(value)
    if (!addressRegex.test(this.value)) {
      throw new Error(`invalid address: ${value}`)
    }
  }

  public static override parse(address: string | AddressSelector): Address {
    return new Address(address)
  }

  public get name(): string | null {
    const index = this.value.lastIndexOf('.')
    const tail = index === -1 ? this.value.replace(/^@/, '') : this.value.slice(index + 1)
    return tail.trim() || null
  }

  public get names(): string[] {
    const path = this.value.slice(1)
    return path.split('.')
  }

  public get depth(): number {
    return [...this.value].filter((current) => current === '.').length + 1
  }

  public append(name: string): Address {
    return new Address(this.value + '.' + name)
  }

  public override get isAbsolute(): boolean {
    return this.isEngine || this.value.startsWith('@')
  }

  /** Whether this addresses the engine root rather than a component. */
  public get isEngine(): boolean {
    return this.value === engineRoot
  }

  public override asAbsolute(root: Address | null): Address {
    if (this.isAbsolute) {
      return this
    } else if (root == null || root.value === '~') {
      return new Address('@' + this.value)
    } else {
      return new Address(`${root.value}.${this.value}`)
    }
  }

  public all(): AddressSelector {
    if (this.value.endsWith(':all')) {
      return this
    }

    return new AddressSelector(this.value + ':all')
  }
}

export const AddressInputModel = z.union([z.string(), z.instanceof(AddressSelector)])
export const AddressModel = AddressInputModel.transform(Address.parse)
export const AddressSelectorModel = AddressInputModel.transform(AddressSelector.parse)
