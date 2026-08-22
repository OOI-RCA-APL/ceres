import { describe, expect, it } from 'vitest'

import { anchoredAtZero } from '@/chart'

describe('anchoredAtZero', () => {
  it('drops the bottom to zero for data above it', () => {
    expect(anchoredAtZero(12, 'min')).toBe(0)
    expect(anchoredAtZero(40, 'max')).toBe(40)
  })

  it('raises the top to zero for data below it', () => {
    expect(anchoredAtZero(-40, 'min')).toBe(-40)
    expect(anchoredAtZero(-12, 'max')).toBe(0)
  })

  it('leaves an extent that already spans zero alone', () => {
    expect(anchoredAtZero(-15, 'min')).toBe(-15)
    expect(anchoredAtZero(15, 'max')).toBe(15)
  })

  it('holds zero at an extent that ends on it', () => {
    expect(anchoredAtZero(0, 'min')).toBe(0)
    expect(anchoredAtZero(0, 'max')).toBe(0)
  })
})
