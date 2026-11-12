import type { Page } from '@playwright/test'

import type { EngineGroup, EngineUser } from './engine'
import { adminMenu, choose, dialog, expect, expectPage, login, notice, test } from './fixtures'

async function openGroup(page: Page, group: EngineGroup): Promise<void> {
  await page.goto(`/groups/${group.id}`)
  await expect(page.getByRole('heading', { name: group.name })).toBeVisible()
}

/** The row for `user` in the group's "Members" list. */
function member(page: Page, user: EngineUser) {
  return page.getByRole('link', { name: user.username })
}

test.describe('groups', () => {
  test.beforeEach(async ({ admin, page }) => {
    await login(page, admin)
  })

  test('the admin menu opens the group list', async ({ page }) => {
    await adminMenu(page).click()
    await page.getByRole('menuitem', { name: 'Groups' }).click()

    await expectPage(page, '/groups')
    await expect(page.getByRole('heading', { name: 'Groups' })).toBeVisible()
  })

  test('an administrator creates a group', async ({ engine, page }) => {
    await page.goto('/groups/create')
    await page.getByLabel('Name').fill('created')
    await page.getByLabel('Description').fill('A group made in the console.')
    await page.getByRole('button', { name: 'Create' }).click()

    await expect(notice(page, 'Group "created" created successfully.')).toBeVisible()
    expect(await engine.group('created')).toMatchObject({
      description: 'A group made in the console.',
    })
  })

  test('a taken group name is refused', async ({ engine, page }) => {
    const group = await engine.createGroup('team')
    await page.goto('/groups/create')

    await page.getByLabel('Name').fill(group.name)
    await page.getByRole('button', { name: 'Create' }).click()

    await expect(notice(page, `Group "${group.name}" already exists.`)).toBeVisible()
  })

  test('an administrator renames a group', async ({ engine, page }) => {
    const group = await engine.createGroup('team')
    await openGroup(page, group)

    await page.getByRole('button', { name: 'Edit' }).click()
    await page.getByLabel('Name').fill(`${group.name}-renamed`)
    await page.getByRole('button', { name: 'Update' }).click()

    await expect(notice(page, `Group "${group.name}-renamed" updated successfully.`)).toBeVisible()
    await expect.poll(() => engine.group(`${group.name}-renamed`)).not.toBeNull()
  })

  test('an administrator adds and removes a member', async ({ engine, page }) => {
    const group = await engine.createGroup('team')
    const user = await engine.createUser('member')
    await openGroup(page, group)

    await page.getByRole('button', { name: 'Add Member' }).click()
    await choose(page.getByRole('dialog', { name: 'Add Member' }), user.username)

    await expect(notice(page, `Added "${user.username}".`)).toBeVisible()
    await expect(page.getByText('Members (1)')).toBeVisible()
    expect(await engine.isMember(user, group)).toBe(true)

    await member(page, user).getByRole('button', { name: 'Remove Member' }).click()
    await expect(dialog(page)).toContainText(`Remove "${user.username}" from this group?`)
    await dialog(page).getByRole('button', { name: 'Remove' }).click()

    await expect(notice(page, `Removed "${user.username}".`)).toBeVisible()
    await expect(page.getByText('Members (0)')).toBeVisible()
    expect(await engine.isMember(user, group)).toBe(false)
  })

  test("an administrator adds a user to a group from the user's page", async ({ engine, page }) => {
    const group = await engine.createGroup('team')
    const user = await engine.createUser('member')
    await page.goto(`/users/${user.id}`)

    await page.getByRole('button', { name: 'Add to Group' }).click()
    await choose(page.getByRole('dialog', { name: 'Add to Group' }), group.name)

    await expect(notice(page, `Added to "${group.name}".`)).toBeVisible()
    await expect(page.getByText('Groups (1)')).toBeVisible()
    expect(await engine.isMember(user, group)).toBe(true)

    await page
      .getByRole('link', { name: group.name })
      .getByRole('button', { name: 'Remove from Group' })
      .click()
    await dialog(page).getByRole('button', { name: 'Remove' }).click()

    await expect(notice(page, `Removed from "${group.name}".`)).toBeVisible()
    expect(await engine.isMember(user, group)).toBe(false)
  })

  test('an administrator deletes a group', async ({ engine, page }) => {
    const group = await engine.createGroup('team')
    await openGroup(page, group)

    await page.getByRole('button', { name: 'Delete Group' }).click()
    await expect(dialog(page)).toContainText('Permanently delete this group?')
    await dialog(page).getByRole('button', { name: 'Delete' }).click()

    await expect(notice(page, 'Group deleted.')).toBeVisible()
    await expectPage(page, '/groups')
    expect(await engine.group(group.name)).toBeNull()
  })
})
