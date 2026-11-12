import type { Page } from '@playwright/test'

import type { AccessLevel, EngineUser } from './engine'
import { dialog, expect, login, notice, test } from './fixtures'

/** Grants `level` on `@device` through the "Add Permission" popover of the open page. */
async function addPermission(page: Page, level: AccessLevel): Promise<void> {
  await page.getByRole('button', { name: 'Add Permission' }).click()
  const popover = page.getByRole('dialog', { name: 'Add Permission' })
  await popover.getByLabel('Can').click()
  await page.getByRole('option', { name: level, exact: false }).click()
  // The target menu's trigger names itself "Show popup" rather than by its field's label.
  await popover.getByRole('button', { name: 'Show popup' }).click()
  await page.getByRole('option', { name: '@device' }).click()
  await popover.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(notice(page, 'Permission added.')).toBeVisible()
}

/** Signs `user` in and opens `@device`, where its "Execute" button shows whether they may act. */
async function openDeviceAs(page: Page, user: EngineUser): Promise<void> {
  await login(page, user)
  await page.goto('/components/@device')
  await expect(page.getByLabel('Seconds')).toBeVisible()
}

test.describe('permissions', () => {
  test.beforeEach(async ({ admin, page }) => {
    await login(page, admin)
  })

  test('a granted user may operate a component', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await page.goto(`/users/${user.id}`)

    await addPermission(page, 'operate')

    await expect(page.getByText('Permissions (1)')).toBeVisible()
    await expect(page.getByText('Effective Access (1)')).toBeVisible()
    await openDeviceAs(page, user)
    await expect(page.getByRole('button', { name: 'Execute' })).toBeEnabled()
  })

  test('a viewer may see a component but not operate it', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await page.goto(`/users/${user.id}`)

    await addPermission(page, 'view')

    await openDeviceAs(page, user)
    await expect(page.getByRole('button', { name: 'Execute' })).toBeDisabled()
  })

  test('removing a permission takes the access away', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await engine.grant(user, '@device', 'operate')
    await page.goto(`/users/${user.id}`)

    await page.getByRole('button', { name: 'Remove Permission' }).click()
    await expect(dialog(page)).toContainText('Remove the permission for "@device"?')
    await dialog(page).getByRole('button', { name: 'Remove' }).click()

    await expect(notice(page, 'Permission removed.')).toBeVisible()
    await expect(page.getByText('Permissions (0)')).toBeVisible()
    await login(page, user)
    await page.goto('/components/@device')
    await expect(page.getByLabel('Seconds')).toBeHidden()
  })

  test("a group's permission reaches its members", async ({ engine, page }) => {
    const group = await engine.createGroup('team')
    const user = await engine.createUser('member')
    await engine.addMember(user, group)
    await page.goto(`/groups/${group.id}`)

    await addPermission(page, 'operate')

    await page.goto(`/users/${user.id}`)
    await expect(
      page.getByRole('link', { name: `@device From group "${group.name}". Operate` }),
    ).toBeVisible()
    await openDeviceAs(page, user)
    await expect(page.getByRole('button', { name: 'Execute' })).toBeEnabled()
  })
})
