import { expect, expectPage, login, notice, submitLogin, test } from './fixtures'

const refusal = 'Failed to log in. Incorrect username or password.'
const turnedAway = 'You do not have access to that resource.'

test.describe('login', () => {
  test('a user signs in and out', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await login(page, user)

    await page.getByRole('link', { name: user.username }).click()
    await page.getByRole('button', { name: 'Sign Out' }).click()

    await expect(notice(page, 'You have signed out.')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Login' })).toBeVisible()
  })

  test('a wrong password is refused', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await page.goto('/login')

    await submitLogin(page, user.username, 'wrong-password')

    await expect(notice(page, refusal)).toBeVisible()
    await expectPage(page, '/login')
  })

  test('an unknown user is refused', async ({ page }) => {
    await page.goto('/login')

    await submitLogin(page, 'nobody')

    await expect(notice(page, refusal)).toBeVisible()
  })

  test('a protected page sends a visitor to log in, then back', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await page.goto('/account')

    await expect(notice(page, turnedAway)).toBeVisible()
    await expectPage(page, '/login', '/account')

    await submitLogin(page, user.username)

    await expectPage(page, '/account')
    await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible()
  })

  test('an administrator page turns away a user who is not one', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await login(page, user)

    await page.goto('/users')

    await expect(notice(page, turnedAway)).toBeVisible()
    await expectPage(page, '/login', '/users')
  })

  test('a disabled user is refused', async ({ engine, page }) => {
    const user = await engine.createUser('member')
    await engine.ceres(
      'users',
      'update',
      '--id',
      user.id,
      '--set',
      '{"disabled": true}',
      '--no-confirm',
    )
    await page.goto('/login')

    await submitLogin(page, user.username)

    await expect(notice(page, 'Failed to log in. This account is disabled.')).toBeVisible()
    await expectPage(page, '/login')
  })
})
