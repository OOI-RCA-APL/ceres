import type { Locator, Page } from '@playwright/test'

import type { Engine } from './engine'
import { expect, login, test } from './fixtures'

/** Logs in as a new administrator and returns the "Procedures" workspace's row, which the engine
stores sized to its contents. A new account each time, since the console saves a user's edits as
that user's draft and a drag would carry into the next test. */
async function proceduresRow(page: Page, engine: Engine): Promise<Locator> {
  await login(page, await engine.createUser('editor', { admin: true }))
  await page.goto('/components/@device')
  const execute = page.getByRole('button', { name: 'Execute' })
  await expect(execute).toBeVisible()
  return page.locator('[data-row]').filter({ has: execute }).last()
}

async function heightOf(locator: Locator): Promise<number> {
  const box = await locator.boundingBox()
  expect(box).not.toBeNull()
  return box!.height
}

/** The grip on the bottom edge of `row`. */
function rowEdge(row: Locator): Locator {
  return row.getByRole('separator', { name: 'Row Height' })
}

/** Drags the bottom edge of `row` down by `distance` pixels. */
async function dragRowEdge(page: Page, row: Locator, distance: number): Promise<void> {
  // The mouse moves in viewport coordinates and the grip sits low on the page.
  await rowEdge(row).scrollIntoViewIfNeeded()
  const box = await rowEdge(row).boundingBox()
  expect(box).not.toBeNull()

  const x = box!.x + box!.width / 2
  const y = box!.y + box!.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x, y + distance, { steps: 5 })
  await page.mouse.up()
}

test.describe('workspace rows', () => {
  test('a row sized to its contents shows all of its widget', async ({ engine, page }) => {
    const row = await proceduresRow(page, engine)

    const rowBox = await row.boundingBox()
    const executeBox = await page.getByRole('button', { name: 'Execute' }).boundingBox()
    expect(rowBox).not.toBeNull()
    expect(executeBox).not.toBeNull()
    expect(executeBox!.y + executeBox!.height).toBeLessThanOrEqual(rowBox!.y + rowBox!.height)
  })

  test('dragging a row fixes its height, and fitting it returns it to its contents', async ({
    engine,
    page,
  }) => {
    const row = await proceduresRow(page, engine)
    const fitted = await heightOf(row)

    await dragRowEdge(page, row, 100)
    await expect.poll(() => heightOf(row)).toBeGreaterThan(fitted + 90)

    await row.click({ button: 'right', position: { x: 20, y: 20 } })
    await page.getByRole('menuitem', { name: 'Fit Row To Content' }).click()
    await expect.poll(() => heightOf(row)).toBeCloseTo(fitted, 0)
  })

  test('double-clicking a row edge returns it to its contents', async ({ engine, page }) => {
    const row = await proceduresRow(page, engine)
    const fitted = await heightOf(row)

    await dragRowEdge(page, row, 100)
    await expect.poll(() => heightOf(row)).toBeGreaterThan(fitted + 90)

    await rowEdge(row).dblclick()
    await expect.poll(() => heightOf(row)).toBeCloseTo(fitted, 0)
  })
})
