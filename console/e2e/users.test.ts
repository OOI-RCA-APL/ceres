import type { Page } from '@playwright/test'

import type { Engine, EngineUserRecord, EngineUser } from './engine'
import { adminMenu, dialog, expect, expectPage, login, notice, test } from './fixtures'

/** Opens `user`'s page from the "Users" list, found by searching for their username. */
async function openUser(page: Page, user: EngineUser): Promise<void> {
  await page.goto('/users')
  await page.getByPlaceholder('Search').fill(user.username)
  await page.getByRole('link', { name: user.username }).click()
  await expectPage(page, `/users/${user.id}`)
}

/** Waits until the engine has stored `username` with `expected` fields. */
async function stored(
  engine: Engine,
  username: string,
  expected: Partial<EngineUserRecord>,
): Promise<void> {
  await expect.poll(() => engine.user(username)).toMatchObject(expected)
}

test.describe('users', () => {
  test.beforeEach(async ({ admin, page }) => {
    await login(page, admin)
  })

  test('the admin menu opens the user list', async ({ page }) => {
    await adminMenu(page).click()
    await page.getByRole('menuitem', { name: 'Users' }).click()

    await expectPage(page, '/users')
    await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
  })

  test('the user list finds a user by email', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await page.goto('/users')

    await page.getByPlaceholder('Search').fill(`${user.username}@example.com`)

    await expect(page.getByRole('link', { name: user.username })).toBeVisible()
  })

  test('an administrator creates a user who can then log in', async ({ engine, page }) => {
    await page.goto('/users/create')
    await page.getByLabel('Username').fill('created')
    await page.getByLabel('Password').fill('created-password')
    await page.getByLabel('Email').fill('created@example.com')
    await page.getByRole('button', { name: 'Create' }).click()

    await expect(notice(page, 'User "created" created successfully.')).toBeVisible()
    const created = await engine.user('created')
    expect(created).not.toBeNull()
    await expectPage(page, `/users/${created?.id}`)

    await login(page, { username: 'created' }, 'created-password')
  })

  test('a taken username is refused', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await page.goto('/users/create')

    await page.getByLabel('Username').fill(user.username)
    await page.getByLabel('Password').fill('abcdefgh')
    await page.getByLabel('Email').fill('another@example.com')
    await page.getByRole('button', { name: 'Create' }).click()

    await expect(notice(page, `User "${user.username}" already exists.`)).toBeVisible()
  })

  test('an administrator edits a user', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await openUser(page, user)

    await page.getByRole('button', { name: 'Edit' }).click()
    await page.getByLabel('Email').fill('edited@example.com')
    await page.getByText('Administrator').click()
    await page.getByRole('button', { name: 'Update' }).click()

    await expect(notice(page, `User "${user.username}" updated successfully.`)).toBeVisible()
    await stored(engine, user.username, { email: 'edited@example.com', admin: true })
  })

  test('an administrator disables a user', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await openUser(page, user)

    await page.getByRole('button', { name: 'Edit' }).click()
    await page.getByText('Disabled').click()
    await page.getByRole('button', { name: 'Update' }).click()

    await expect(notice(page, `User "${user.username}" updated successfully.`)).toBeVisible()
    await stored(engine, user.username, { disabled: true })
  })

  test('canceling an edit keeps the stored user', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await openUser(page, user)

    await page.getByRole('button', { name: 'Edit' }).click()
    await page.getByLabel('Email').fill('discarded@example.com')
    await page.getByRole('button', { name: 'Cancel' }).click()

    await expect(page.getByLabel('Email')).toHaveValue(`${user.username}@example.com`)
    await stored(engine, user.username, { email: `${user.username}@example.com` })
  })

  test("an administrator assigns a user's password", async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await openUser(page, user)

    await page.getByRole('button', { name: 'Change Password' }).click()
    await expect(dialog(page).getByPlaceholder('Current Password')).toBeHidden()
    await dialog(page).getByPlaceholder('New Password').fill('assigned-password')
    await dialog(page).getByRole('button', { name: 'Submit' }).click()

    await expect(
      notice(page, `Password for "${user.username}" changed successfully.`),
    ).toBeVisible()
    await login(page, user, 'assigned-password')
  })

  test('an administrator deletes a user', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await openUser(page, user)

    await page.getByRole('button', { name: 'Delete' }).click()
    await expect(dialog(page)).toContainText(`Permanently delete user "${user.username}"?`)
    await dialog(page).getByRole('button', { name: 'Delete' }).click()

    await expect(notice(page, `User "${user.username}" deleted successfully.`)).toBeVisible()
    await expectPage(page, '/users')
    expect(await engine.user(user.username)).toBeNull()
  })
})
