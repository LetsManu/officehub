/**
 * Minimal, safe Markdown renderer for policy documents.
 * All text is HTML-escaped first; only a small set of formatting is produced by this code.
 * Supported: headings, paragraphs, bullet and numbered lists, bold, italic, inline code, links.
 */

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function inline(text: string): string {
  let html = escapeHtml(text)
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
  // Only http(s) and mailto links; the URL was escaped above, so it cannot break out of the attribute.
  html = html.replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:)[^)\s]+)\)/g, '<a href="$2" rel="noopener noreferrer" target="_blank">$1</a>')
  return html
}

export function renderMarkdown(source: string): string {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const out: string[] = []
  let paragraph: string[] = []
  let list: { tag: 'ul' | 'ol'; items: string[] } | null = null

  const flushParagraph = () => {
    if (paragraph.length) out.push(`<p>${inline(paragraph.join(' '))}</p>`)
    paragraph = []
  }
  const flushList = () => {
    if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`)
    list = null
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)

    if (!line.trim()) {
      flushParagraph()
      flushList()
    } else if (heading) {
      flushParagraph()
      flushList()
      // Document headings start at h2 because the page already has an h1.
      const level = Math.min(heading[1].length + 1, 5)
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
    } else if (bullet || numbered) {
      flushParagraph()
      const tag = bullet ? 'ul' : 'ol'
      if (!list || list.tag !== tag) {
        flushList()
        list = { tag, items: [] }
      }
      list.items.push((bullet ?? numbered)![1])
    } else {
      flushList()
      paragraph.push(line.trim())
    }
  }
  flushParagraph()
  flushList()
  return out.join('\n')
}

/**
 * Chat messages: like the renderer above, but line breaks stay, ```code blocks```, ~~strike~~, bare links become
 * clickable and @mentions of members are highlighted. Everything is escaped first.
 */
export function renderChat(source: string, names: string[] = []): string {
  const blocks = source.replace(/\r\n?/g, '\n').split(/```/)
  const html = blocks
    .map((block, i) => {
      if (i % 2 === 1) return `<pre><code>${escapeHtml(block.replace(/^\n|\n$/g, ''))}</code></pre>`
      return block
        .split('\n')
        .map((line) => {
          const bullet = /^\s*[-*]\s+/.test(line)
          let out = inline(bullet ? line.replace(/^\s*[-*]\s+/, '') : line)
          out = out.replace(/~~([^~]+)~~/g, '<s>$1</s>')
          out = out.replace(/(^|[\s(])(https?:\/\/[^\s<]+[^\s<.,;:!?)])/g, '$1<a href="$2" rel="noopener noreferrer" target="_blank">$2</a>')
          return bullet ? `• ${out}` : out
        })
        .join('<br>')
    })
    .join('')
  if (!names.length) return html
  const escaped = [...names].sort((a, b) => b.length - a.length).map((n) => escapeHtml(`@${n}`).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  return html.replace(new RegExp(`(${escaped.join('|')})`, 'g'), '<span class="mention">$1</span>')
}
