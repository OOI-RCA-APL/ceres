import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

import CCardPage from '@/components/c-card-page.vue'

const Page = { template: '<div />' }

/** A router as the app makes one, after the browser opened `/users` directly. */
async function openedDirectly() {
  window.history.replaceState(null, '', '/users')
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/users', component: Page },
      { path: '/trust', component: Page },
    ],
  })
  await router.push('/users')
  await router.isReady()
  return router
}

async function render() {
  const router = await openedDirectly()
  const page = mount(CCardPage, {
    props: { title: 'Users' },
    global: {
      plugins: [router, createPinia()],
      stubs: {
        'c-tooltip': { template: '<div data-back><slot /></div>' },
        'c-button': true,
        'c-text': { template: '<h1><slot /></h1>' },
        'c-separator': true,
      },
    },
  })
  return { router, page }
}

describe('c-card-page', () => {
  it('hides the back arrow on the first page the app opened', async () => {
    const { page } = await render()

    expect(window.history.state.back).toBeNull()
    expect(page.find('[data-back]').exists()).toBe(false)
  })

  it('shows the back arrow once the app navigated to the page', async () => {
    const { router, page } = await render()
    await router.push('/trust')

    expect(window.history.state.back).toBe('/users')
    expect(page.find('[data-back]').exists()).toBe(true)
  })
})
