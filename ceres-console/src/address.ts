export class Address {
  private value: string

  constructor(value: string | Address) {
    if (typeof value === 'string') {
      if (!value.startsWith('@')) {
        throw new Error('Address must start with "@"')
      }
    }

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
}
