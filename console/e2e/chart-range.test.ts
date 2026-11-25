import type { Locator, Page } from '@playwright/test'

import { expect, login, test } from './fixtures'

/** Opens `@device` and returns its "Readings" chart once it has asked for its records. */
async function openChart(page: Page): Promise<Locator> {
  const loaded = page.waitForRequest(/\/api\/particles\?/)
  await page.goto('/components/@device')
  const chart = page.locator('[data-widget-id]').filter({ hasText: 'Readings' })
  await chart.scrollIntoViewIfNeeded()
  await loaded
  return chart
}

/** The range bar's label, which opens the range popover. */
function rangeLabel(chart: Locator): Locator {
  return chart.getByRole('button', { name: /^Last |UTC$/ })
}

/** The particle query the next load sends, once `action` starts it. */
async function nextQuery(page: Page, action: () => Promise<void>): Promise<URLSearchParams> {
  const [request] = await Promise.all([page.waitForRequest(/\/api\/particles\?/), action()])
  return new URL(request.url()).searchParams
}

test.describe('chart range', () => {
  test.beforeEach(async ({ admin, page }) => {
    await login(page, admin)
  })

  test('paging back fixes the range, and "Live" follows new data again', async ({ page }) => {
    const chart = await openChart(page)
    await expect(rangeLabel(chart)).toHaveText('Last 1 h')

    const query = await nextQuery(page, () =>
      chart.getByRole('button', { name: 'Earlier' }).click(),
    )
    expect(query.get('before')).not.toBeNull()
    await expect(rangeLabel(chart)).toHaveText(/ to .* UTC$/)

    await chart.getByRole('button', { name: 'Live' }).click()
    await expect(rangeLabel(chart)).toHaveText('Last 1 h')
  })

  test('a preset resumes live over its span', async ({ page }) => {
    const chart = await openChart(page)

    await rangeLabel(chart).click()
    const query = await nextQuery(page, () =>
      page.getByRole('button', { name: 'Last 6 h', exact: true }).click(),
    )

    expect(query.get('before')).toBeNull()
    await expect(rangeLabel(chart)).toHaveText('Last 6 h')
  })

  test('a typed range applies only on "Apply"', async ({ page }) => {
    const chart = await openChart(page)

    await rangeLabel(chart).click()
    await page.getByLabel('Start').fill('2026-01-02 00:00')
    await page.getByLabel('End').fill('2026-01-03 00:00')
    await expect(rangeLabel(chart)).toHaveText('Last 1 h')

    const query = await nextQuery(page, () => page.getByRole('button', { name: 'Apply' }).click())
    expect(query.get('after')).toBe('2026-01-02T00:00:00.000Z')
    expect(query.get('before')).toBe('2026-01-03T00:00:00.000Z')
    await expect(rangeLabel(chart)).toHaveText('2026-01-02 00:00 to 2026-01-03 00:00 UTC')
  })

  test('dragging across the plot zooms, and a double click returns', async ({ page }) => {
    const chart = await openChart(page)
    const plot = chart.locator('canvas').first()
    const box = await plot.boundingBox()
    expect(box).not.toBeNull()

    const y = box!.y + box!.height / 2
    await page.mouse.move(box!.x + box!.width * 0.4, y)
    await page.mouse.down()
    await page.mouse.move(box!.x + box!.width * 0.6, y, { steps: 5 })
    await page.mouse.up()

    await expect(chart.getByRole('button', { name: 'Reset Zoom' })).toBeVisible()
    await expect(rangeLabel(chart)).toHaveText(/ to .* UTC$/)

    await plot.dblclick()
    await expect(chart.getByRole('button', { name: 'Reset Zoom' })).toBeHidden()
    await expect(rangeLabel(chart)).toHaveText('Last 1 h')
  })
})
