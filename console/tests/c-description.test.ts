import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import CDescription from '@/components/c-description.vue'
import { renderMarkdown } from '@/markdown'
import { lineBottoms } from '@/text-lines'

vi.mock('@/text-lines', () => ({ lineBottoms: vi.fn(() => []) }))

describe('rendering a description as Markdown', () => {
  it('joins wrapped lines and keeps paragraphs, lists and code', () => {
    const html = renderMarkdown('One line\nwrapped.\n\n- a\n- b\n\nUse `run()`.')
    expect(html).toContain('<p>One line\nwrapped.</p>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<code>run()</code>')
  })

  it('leaves raw HTML as text', () => {
    const html = renderMarkdown('<script>alert(1)</script> <b>bold</b>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;b&gt;bold&lt;/b&gt;')
  })

  it('opens links in a new tab and refuses script links', () => {
    expect(renderMarkdown('[docs](https://example.com)')).toContain(
      '<a href="https://example.com" target="_blank" rel="noopener noreferrer">docs</a>',
    )
    expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('href="javascript:')
  })
})

/** Mount a description laid out as this many 15px lines, which happy-dom never does itself. */
async function laidOut(lines: number) {
  vi.mocked(lineBottoms).mockReturnValue(
    Array.from({ length: lines }, (_, line) => (line + 1) * 15),
  )
  const description = mount(CDescription, {
    props: { text: 'abc' },
    global: { stubs: { 'c-icon': true } },
  })
  await nextTick()
  return description
}

describe('c-description', () => {
  it('offers no fold when the text fits or one line would hide', async () => {
    expect((await laidOut(3)).find('button').exists()).toBe(false)
    expect((await laidOut(4)).find('button').exists()).toBe(false)
  })

  it('folds after the last whole line shown and toggles the rest', async () => {
    const description = await laidOut(7)

    const content = description.find('.c-description')
    expect(content.attributes('style')).toContain('max-height: 45px')
    expect(description.find('button').text()).toBe('4 more lines')

    await description.find('button').trigger('click')
    expect(content.attributes('style')).toBeUndefined()
    expect(description.find('button').text()).toBe('Fold')

    await description.find('button').trigger('click')
    expect(content.attributes('style')).toContain('max-height: 45px')
  })
})
