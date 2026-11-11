import type { Page } from '@playwright/test'

import { expect, login, test, type Engine } from './engine'

/** Opens `@device` as the admin and calls `hold` for `seconds`. */
async function hold(page: Page, seconds: number): Promise<void> {
  await login(page, 'admin')
  await page.goto('/components/@device')
  await page.getByLabel('Seconds').fill(String(seconds))
  await page.getByRole('button', { name: 'Execute' }).click()
}

/** Waits until `@device` has logged a line containing `text` `count` times. */
async function logged(engine: Engine, text: string, count: number): Promise<void> {
  // The engine stores its logs in batches, so an entry can land after the page has moved on.
  await expect.poll(async () => (await engine.logs('@device', text)).length).toBe(count)
}

test.describe('procedures', () => {
  test('an action called from the console runs on the engine', async ({ engine, page }) => {
    const finished = (await engine.logs('@device', 'hold finished')).length
    await hold(page, 0.1)

    await expect(page.getByText('held')).toBeVisible()
    await logged(engine, 'hold finished', finished + 1)
  })

  test('aborting a running action cancels it on the engine', async ({ engine, page }) => {
    const cancelled = (await engine.logs('@device', 'hold cancelled')).length
    await hold(page, 30)

    await page.getByRole('button', { name: 'Abort' }).click()

    await expect(page.getByRole('button', { name: 'Abort' })).toBeHidden()
    await logged(engine, 'hold cancelled', cancelled + 1)
  })

  test('leaving the page cancels a running action', async ({ engine, page }) => {
    const cancelled = (await engine.logs('@device', 'hold cancelled')).length
    await hold(page, 30)
    await expect(page.getByRole('button', { name: 'Abort' })).toBeVisible()

    await page.goto('/')

    await logged(engine, 'hold cancelled', cancelled + 1)
  })

  test('a viewer cannot execute an action', async ({ page }) => {
    await login(page, 'viewer')
    await page.goto('/components/@device')

    await expect(page.getByLabel('Seconds')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Execute' })).toBeDisabled()
  })
})
