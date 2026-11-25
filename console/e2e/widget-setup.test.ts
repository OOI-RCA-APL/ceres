import type { Page } from '@playwright/test'

import type { Engine } from './engine'
import { expect, login, test } from './fixtures'

/** Logs in as a new administrator, since the console saves a user's edits as that user's draft,
and adds `kind` to the end of the workspace through its "Add Widget" button. */
async function addWidget(page: Page, engine: Engine, kind: string): Promise<void> {
  await login(page, await engine.createUser('editor', { admin: true }))
  await page.goto('/components/@device')
  const add = page.getByRole('button', { name: 'Add Widget' }).last()
  await add.scrollIntoViewIfNeeded()
  await add.click()
  await page.getByRole('menuitem', { name: kind, exact: true }).click()
}

test.describe('a new chart or meter', () => {
  for (const kind of ['Chart', 'Meter']) {
    test(`a ${kind.toLowerCase()} opens on its data picker, ready to search`, async ({
      engine,
      page,
    }) => {
      await addWidget(page, engine, kind)

      await expect(page.getByRole('dialog')).toBeVisible()
      await expect(page.getByRole('textbox', { name: 'Search Data' })).toBeFocused()
    })
  }

  test('an empty chart offers "Choose Data", which opens its settings', async ({
    engine,
    page,
  }) => {
    await addWidget(page, engine, 'Chart')
    await page.getByRole('button', { name: 'Done' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()

    await page.getByRole('button', { name: 'Choose Data' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
  })
})
