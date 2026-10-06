import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { AuthFeaturesModel } from '@/api/auth'
import CTrustLink from '@/components/c-trust-link.vue'

function render(authority: { fingerprint: string } | null) {
  return mount(CTrustLink, {
    props: { authority },
    global: {
      stubs: { 'c-button': { props: ['label', 'to'], template: '<a :href="to">{{ label }}</a>' } },
    },
  })
}

describe('c-trust-link', () => {
  it('links to the trust page when the server manages its certificate', () => {
    const link = render({ fingerprint: 'AB:CD' }).find('a')

    expect(link.text()).toBe('Trust this server?')
    expect(link.attributes('href')).toBe('/trust')
  })

  it('renders nothing without a managed certificate', () => {
    expect(render(null).html()).toBe('<!--v-if-->')
  })
})

describe('AuthFeaturesModel', () => {
  it('reads the authority a managed certificate offers', () => {
    const features = AuthFeaturesModel.parse({
      impersonate: false,
      authority: { fingerprint: 'AB' },
    })

    expect(features.authority).toEqual({ fingerprint: 'AB' })
  })

  it('reads a server without one', () => {
    expect(AuthFeaturesModel.parse({ impersonate: true, authority: null }).authority).toBeNull()
  })
})
