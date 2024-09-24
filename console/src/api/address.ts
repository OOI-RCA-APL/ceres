import Zod from 'zod'

const namePattern = '^[a-zA-Z_-][a-zA-Z0-9_-]*$'
const name = namePattern.slice(1, -1)
const modifier = ':(all|children|descendants)'
const segment = `\\~(${modifier})?|@?[a-z-A-Z_\\-.]+(${modifier})?|@(${modifier})?|${modifier}`

const addressSelectorRegex = new RegExp(`^${segment}(\\|${segment})*$`)

export class AddressSelector {
  public readonly value: string

  constructor(value: string | AddressSelector) {
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
}

export const AddressSelectorModel = Zod.string().transform(AddressSelector.parse)

const addressRegex = new RegExp(`^~|@(${name}(\\.${name})*)*$`)

export class Address extends AddressSelector {
  constructor(value: string | AddressSelector) {
    value = value.toString().trim()
    if (!new RegExp(addressRegex).test(value)) {
      throw new Error(`invalid address: ${value}`)
    }

    super(value)
  }

  public static parse(address: string | AddressSelector): Address {
    return new Address(address)
  }

  public get isRoot(): boolean {
    return this.value === '@'
  }

  public get name(): string | null {
    if (this.isRoot) {
    }

    return this.value.slice(this.value.lastIndexOf('.') + 1).trim() || null
  }

  public get names(): string[] {
    const path = this.value.slice(1)
    return path.split('.')
  }

  public get depth(): number {
    if (this.isRoot) {
      return 0
    }

    return [...this.value].filter((current) => current === '.').length + 1
  }

  public append(name: string): Address {
    if (this.isRoot) {
      return new Address('@' + name)
    }

    return new Address(this.value + '.' + name)
  }

  public all(): AddressSelector {
    if (this.value.endsWith(':all')) {
      return this
    }

    return new AddressSelector(this.value + ':all')
  }
}

export const AddressModel = Zod.string().transform(Address.parse)
