import type { Page } from '@playwright/test'

import { dialog, expect, login, notice, test } from './fixtures'

/** Opens the signed-in user's own account page. */
async function openAccount(page: Page): Promise<void> {
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible()
}

/** Submits the "Change Password" dialog of the account page. */
async function changePassword(page: Page, current: string, next: string): Promise<void> {
  await page.getByRole('button', { name: 'Change Password' }).click()
  await dialog(page).getByPlaceholder('Current Password').fill(current)
  await dialog(page).getByPlaceholder('New Password').fill(next)
  await dialog(page).getByRole('button', { name: 'Submit' }).click()
}

test.describe('account', () => {
  test('a user changes their own email', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await login(page, user)
    await openAccount(page)

    await page.getByRole('button', { name: 'Edit' }).click()
    await page.getByLabel('Email').fill('changed@example.com')
    await page.getByRole('button', { name: 'Update' }).click()

    await expect(notice(page, 'Account updated successfully.')).toBeVisible()
    expect((await engine.user(user.username))?.email).toBe('changed@example.com')
  })

  test('a user cannot change their own access', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await login(page, user)
    await openAccount(page)

    await page.getByRole('button', { name: 'Edit' }).click()

    await expect(page.getByLabel('Username')).toBeEditable()
    await expect(page.getByText('Administrator')).toBeHidden()
    await expect(page.getByText('Disabled')).toBeHidden()
  })

  test('a user changes their own password', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await login(page, user)
    await openAccount(page)

    await changePassword(page, 'abcdefgh', 'changed-password')

    await expect(
      notice(page, `Password for "${user.username}" changed successfully.`),
    ).toBeVisible()
    await login(page, user, 'changed-password')
  })

  test('a wrong current password changes nothing', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await login(page, user)
    await openAccount(page)

    await changePassword(page, 'wrong-password', 'changed-password')

    await expect(
      notice(page, 'Failed to change password. Current password is incorrect.'),
    ).toBeVisible()
    await login(page, user)
  })
})
