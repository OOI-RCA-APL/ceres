import Zod from 'zod'

/** The address of the engine root, the placement of anything not bound to a component. */
export const engineRoot = '~'

const namePattern = '^[a-zA-Z_-][a-zA-Z0-9_-]*$'
const name = namePattern.slice(1, -1)
const modifier = ':(all|children|descendants)'
const base = `@?${name}(\\.${name})*`
const segment = `\\~(:(all|descendants))?|${base}(${modifier})?|@${modifier}|${modifier}`

const addressSelectorRegex = new RegExp(`^(?:${segment})(?:\\|(?:${segment}))*$`)

export class AddressSelector {
  public readonly value: string

  constructor(value: string | AddressSelector) {
    if (typeof value !== 'string' && !(value instanceof AddressSelector)) {
      throw new Error(`invalid address selector: ${value}`)
    }

    value = value.toString().trim()
    if (!new RegExp(addressSelectorRegex).test(value)) {
      throw new Error(`invalid address selector: ${value}`)
    }

    this.value = value.toString().trim()
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
}

const addressRegex = new RegExp(`^(?:~|@?${name}(\\.${name})*)$`)

export class Address extends AddressSelector {
  constructor(value: string | AddressSelector) {
    if (typeof value !== 'string' && !(value instanceof AddressSelector)) {
      throw new Error(`invalid address selector: ${value}`)
    }

    value = value.toString().trim()
    if (!new RegExp(addressRegex).test(value)) {
      throw new Error(`invalid address: ${value}`)
    }

    super(value)
  }

  public static parse(address: string | AddressSelector): Address {
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

  public get isAbsolute(): boolean {
    return this.isEngine || this.value.startsWith('@')
  }

  /** Whether this addresses the engine root rather than a component. */
  public get isEngine(): boolean {
    return this.value === engineRoot
  }

  public asAbsolute(root: Address | null): Address {
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

export const AddressInputModel = Zod.union([Zod.string(), Zod.instanceof(AddressSelector)])
export const AddressModel = AddressInputModel.transform(Address.parse)
export const AddressSelectorModel = AddressInputModel.transform(AddressSelector.parse)
