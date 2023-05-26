export class Address {
  private value: string

  constructor(value: string | Address) {
    this.value = value.toString().trim()
  }

  public static parse(address: string | Address): Address {
    return new Address(address)
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

  public get isRoot(): boolean {
    return this.value === ''
  }

  public get head(): string | null {
    return this.value.slice(0, this.value.indexOf('.')).trim() || null
  }

  public get unit(): string | null {
    return this.head
  }

  public get name(): string | null {
    return this.value.slice(this.value.lastIndexOf('.') + 1).trim() || null
  }

  public get path(): string[] {
    return this.value.split('.').filter((current) => current)
  }

  public get depth(): number {
    if (this.value === '') {
      return 0
    }

    return [...this.value].filter((current) => current === '.').length + 1
  }

  public concat(other: Address | string): Address {
    if (this.value === '') {
      return new Address(other)
    }

    return new Address(this.value + '.' + other)
  }
}
