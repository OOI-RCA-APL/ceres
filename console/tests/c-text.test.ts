import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CText, { type TextVariant, variantClasses } from '@/components/base/c-text.vue'

const variants = Object.keys(variantClasses) as TextVariant[]

describe('c-text', () => {
  it('renders every variant with its classes', () => {
    for (const variant of variants) {
      const wrapper = mount(CText, {
        props: { variant },
        slots: { default: 'Sample' },
      })
      expect(wrapper.element.tagName).toBe('DIV')
      expect(wrapper.classes().join(' ')).toBe(variantClasses[variant])
      expect(wrapper.text()).toBe('Sample')
    }
  })

  it('renders the requested element', () => {
    const wrapper = mount(CText, {
      props: { variant: 'title1', element: 'h1' },
      slots: { default: 'Heading' },
    })
    expect(wrapper.element.tagName).toBe('H1')
  })
})
