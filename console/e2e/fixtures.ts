import { test as base, expect, type Locator, type Page } from '@playwright/test'

import { Engine, password, type EngineUser } from './engine'

/** Each worker's engine listens on its own port, so workers never share an engine. */
const basePort = 18500

type Fixtures = {
  /** Attaches the engine log to a failed test. */
  engineLog: undefined
}

type WorkerFixtures = {
  engine: Engine
  /** An administrator shared by the worker's tests, which never change it. */
  admin: EngineUser
}

export const test = base.extend<Fixtures, WorkerFixtures>({
  engine: [
    // Playwright reads a fixture's dependencies from its first parameter's destructuring.
    // eslint-disable-next-line no-empty-pattern
    async ({}, use, workerInfo) => {
      const engine = await Engine.start(basePort + workerInfo.parallelIndex)
      await use(engine)
      await engine.stop()
    },
    { scope: 'worker' },
  ],
  admin: [
    async ({ engine }, use) => {
      await use(await engine.createUser('admin', { admin: true }))
    },
    { scope: 'worker' },
  ],
  engineLog: [
    async ({ engine }, use, testInfo) => {
      await use(undefined)
      if (testInfo.status !== testInfo.expectedStatus) {
        await testInfo.attach('engine.log', { path: engine.logPath, contentType: 'text/plain' })
      }
    },
    { auto: true },
  ],
  baseURL: async ({ engine }, use) => {
    await use(engine.url)
  },
})

export { expect }

/** Fills in and submits the login form, staying wherever the console goes next. */
export async function submitLogin(
  page: Page,
  username: string,
  userPassword = password,
): Promise<void> {
  await page.getByPlaceholder('Username').fill(username)
  await page.getByPlaceholder('Password').fill(userPassword)
  await page.getByRole('button', { name: 'Submit' }).click()
}

/** Signs `user` in and waits for the home page. */
export async function login(
  page: Page,
  user: Pick<EngineUser, 'username'>,
  userPassword = password,
): Promise<void> {
  // A cookie left from an earlier sign-in would answer before the login page does.
  await page.context().clearCookies()
  await page.goto('/login')
  await submitLogin(page, user.username, userPassword)
  await expect(notice(page, `Logged in as "${user.username}".`)).toBeVisible()
  await expectPage(page, '/')
}

/** Waits for the console to show the page at `pathname`, sent there to log in first when
`redirect` is set.

The engine serves each page's path with a trailing slash, which this ignores. */
export async function expectPage(page: Page, pathname: string, redirect?: string): Promise<void> {
  await expect(page).toHaveURL((url) => {
    const target = url.searchParams.get('redirect')
    return (
      withoutTrailingSlash(url.pathname) === pathname &&
      (redirect == null || (target != null && withoutTrailingSlash(target) === redirect))
    )
  })
}

function withoutTrailingSlash(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/$/, '') : pathname
}

/** The toast carrying `text`. */
export function notice(page: Page, text: string): Locator {
  return page.getByText(text, { exact: true })
}

/** The open dialog, such as a confirmation before a destructive change. */
export function dialog(page: Page): Locator {
  return page.getByRole('dialog')
}

/** The drawer's "Admin" menu, shown only to administrators. */
export function adminMenu(page: Page): Locator {
  return page.locator('[aria-haspopup="menu"]', { hasText: 'Admin' })
}

/** Chooses `name` from an open user or group chooser, searching for it first. */
export async function choose(chooser: Locator, name: string): Promise<void> {
  await chooser.getByRole('textbox').fill(name)
  // An option's name runs on into its description, so match the label alone.
  await chooser
    .getByRole('option')
    .filter({ has: chooser.page().getByText(name, { exact: true }) })
    .click()
}
