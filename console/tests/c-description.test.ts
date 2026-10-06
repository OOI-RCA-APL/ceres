import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import CDescription from '@/components/c-description.vue'
import { renderMarkdown } from '@/markdown'

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

/** Make every element report the given heights, which happy-dom never lays out. */
function heights(scroll: number, client: number) {
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(scroll)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(client)
}

describe('c-description', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('offers nothing more when the text fits', async () => {
    heights(40, 40)
    const description = mount(CDescription, { props: { text: 'Short.' } })
    await nextTick()

    expect(description.find('button').exists()).toBe(false)
  })

  it('cuts long text and toggles the rest', async () => {
    heights(200, 45)
    const description = mount(CDescription, { props: { text: 'Long.\n\nMore.\n\nMore.' } })
    await nextTick()

    const content = description.find('.c-description')
    const button = description.find('button')
    expect(content.classes()).toContain('c-description-clamped')
    expect(button.text()).toBe('Show more')

    await button.trigger('click')
    expect(content.classes()).not.toContain('c-description-clamped')
    expect(description.find('button').text()).toBe('Show less')

    await description.find('button').trigger('click')
    expect(content.classes()).toContain('c-description-clamped')
  })
})
