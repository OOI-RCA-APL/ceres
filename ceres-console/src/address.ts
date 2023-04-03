export class Address extends String {
  constructor(address: string | Address) {
    const split = address.split('.')
    if (split.length !== 2) {
      throw new Error(`invalid address: ${address}`)
    }

    super(address)
  }

  public static parse(address: string | Address): Address {
    return new Address(address)
  }

  public get unit(): string {
    return this.slice(0, this.indexOf('.'))
  }

  public get component(): string {
    return this.slice(this.indexOf('.') + 1)
  }
}
