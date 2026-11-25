import type { Page } from '@playwright/test'

import { dialog, expect, login, test } from './fixtures'

const latest = '**/_nuxt/builds/latest.json*'

/** Have the engine report a console build other than the one this page runs. */
async function upgrade(page: Page) {
  await page.route(latest, (route) => route.fulfill({ json: { id: '99.0.0', timestamp: 1 } }))
}

/** Bring the page back into view, which makes the console check the build the engine serves. */
async function revisit(page: Page) {
  const checked = page.waitForResponse(latest)
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await checked
}

test.describe('console updates', () => {
  test('an outdated page asks to reload', async ({ admin, page }) => {
    await login(page, admin)
    await upgrade(page)

    await revisit(page)

    await expect(dialog(page)).toContainText('Ceres Updated')
    await expect(dialog(page)).toContainText('The engine now runs Ceres 99.0.0')
    await page.keyboard.press('Escape')
    await expect(dialog(page)).toBeVisible()
  })

  test('reloading loads the console the engine serves', async ({ admin, page }) => {
    await login(page, admin)
    await upgrade(page)
    await revisit(page)

    await page.unroute(latest)
    const reloaded = page.waitForEvent('load')
    await dialog(page).getByRole('button', { name: 'Reload' }).click()
    await reloaded
    await expect(page.getByRole('link', { name: admin.username })).toBeVisible()
    await revisit(page)

    await expect(dialog(page)).toBeHidden()
  })

  test('a current page shows nothing', async ({ admin, page }) => {
    await login(page, admin)

    await revisit(page)

    await expect(dialog(page)).toBeHidden()
  })
})
