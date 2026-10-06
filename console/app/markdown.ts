import MarkdownIt from 'markdown-it'

// Raw HTML stays text, since a docstring comes from code the console does not control. Single
// newlines join into one paragraph, the way a wrapped docstring line reads.
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: false })

// Links leave the console in a new tab, never in place of it.
const renderLinkOpen =
  markdown.renderer.rules.link_open ??
  ((tokens, index, options, _env, self) => self.renderToken(tokens, index, options))
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index]!
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
  return renderLinkOpen(tokens, index, options, env, self)
}

/** Render Markdown text, a docstring or a field's description, to HTML safe to insert. */
export function renderMarkdown(text: string): string {
  return markdown.render(text)
}
