import type { Locator, Page } from '@playwright/test'

import type { Engine } from './engine'
import { expect, login, test } from './fixtures'

/** Logs in as a new administrator and opens `@device`, whose workspace holds a bar of "Echo" and
"Hold" buttons. A new account each time, since the console saves a user's edits as that user's
draft. */
async function openBar(page: Page, engine: Engine): Promise<Locator> {
  await login(page, await engine.createUser('editor', { admin: true }))
  await page.goto('/components/@device')
  const bar = page.locator('[data-widget-id]').filter({ hasText: 'Controls' })
  await expect(bar.getByRole('button', { name: 'Hold' })).toBeVisible()
  // The mouse moves in viewport coordinates and the bar sits below the fold.
  await bar.scrollIntoViewIfNeeded()

  return bar
}

/** The left edge of each named button in `bar`, to read their order from. */
async function leftOf(bar: Locator, name: string): Promise<number> {
  const box = await bar.getByRole('button', { name, exact: true }).boundingBox()
  expect(box).not.toBeNull()
  return box!.x
}

test.describe('buttons', () => {
  test('a button runs its procedure', async ({ engine, page }) => {
    const finished = (await engine.logs('@device', 'hold finished')).length
    const bar = await openBar(page, engine)

    await bar.getByRole('button', { name: 'Hold' }).click()

    await expect
      .poll(async () => (await engine.logs('@device', 'hold finished')).length)
      .toBe(finished + 1)
  })

  test('dragging a button past another reorders them, without pressing it', async ({
    engine,
    page,
  }) => {
    const bar = await openBar(page, engine)
    const echo = await bar.getByRole('button', { name: 'Echo' }).boundingBox()
    const hold = await bar.getByRole('button', { name: 'Hold' }).boundingBox()
    expect(echo).not.toBeNull()
    expect(hold).not.toBeNull()

    await page.mouse.move(echo!.x + echo!.width / 2, echo!.y + echo!.height / 2)
    await page.mouse.down()
    await page.mouse.move(hold!.x + hold!.width - 2, hold!.y + hold!.height / 2, { steps: 10 })
    // A target opens the layout only once it has been held.
    await page.waitForTimeout(400)
    await page.mouse.up()

    await expect
      .poll(async () => (await leftOf(bar, 'Hold')) < (await leftOf(bar, 'Echo')))
      .toBe(true)
    await expect(page.getByRole('dialog')).toBeHidden()
    // The bar stays the height it was stored at.
    expect((await bar.boundingBox())?.height).toBeLessThan(80)
  })

  test('a section laying out buttons adds another', async ({ engine, page }) => {
    const bar = await openBar(page, engine)
    await bar.hover()

    await bar.getByRole('button', { name: 'Add Button' }).click()

    await expect(bar.getByRole('button', { name: 'Button', exact: true })).toBeVisible()
  })
})
