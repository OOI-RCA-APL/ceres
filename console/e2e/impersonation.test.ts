import type { Page } from '@playwright/test'

import type { EngineUser } from './engine'
import { adminMenu, choose, dialog, expect, login, test } from './fixtures'

/** Signs `admin` in and takes on `user`'s identity from the "Admin" menu. */
async function impersonate(page: Page, admin: EngineUser, user: EngineUser): Promise<void> {
  await login(page, admin)
  await adminMenu(page).click()
  await page.getByRole('menuitem', { name: 'Impersonate' }).click()
  await choose(dialog(page), user.username)
  await expect(returnButton(page, user)).toBeVisible()
}

/** The drawer's button back to the administrator's own account. */
function returnButton(page: Page, user: EngineUser) {
  return page.getByRole('button', { name: `Impersonating ${user.username}` })
}

test.describe('impersonation', () => {
  test("an administrator takes on a user's access", async ({ admin, engine, page }) => {
    const user = await engine.createUser('member')
    await engine.grant(user, '@device', 'view')

    await impersonate(page, admin, user)

    await expect(page.getByRole('link', { name: user.username })).toBeVisible()
    await expect(adminMenu(page)).toBeHidden()
    await page.goto('/components/@device')
    await expect(page.getByRole('button', { name: 'Execute' })).toBeDisabled()
  })

  test('an administrator returns to their own account', async ({ admin, engine, page }) => {
    const user = await engine.createUser('member')
    await engine.grant(user, '@device', 'view')
    await impersonate(page, admin, user)
    await page.goto('/components/@device')

    await returnButton(page, user).click()

    await expect(returnButton(page, user)).toBeHidden()
    await expect(adminMenu(page)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Execute' })).toBeEnabled()
  })
})
