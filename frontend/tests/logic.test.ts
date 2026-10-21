import { describe, expect, it } from 'vitest'
import { escapeHtml, renderChat, renderMarkdown } from '../src/lib/markdown'
import { parseSlash, slashMatches } from '../src/lib/slash'
import { countWorkingDays } from '../src/lib/workdays'

describe('countWorkingDays', () => {
  it('counts Monday to Friday', () => {
    expect(countWorkingDays('2026-10-19', '2026-10-25')).toBe(5)
    expect(countWorkingDays('2026-10-24', '2026-10-25')).toBe(0)
    expect(countWorkingDays('2026-10-22', '2026-10-27')).toBe(4)
  })

  it('returns 0 for invalid ranges', () => {
    expect(countWorkingDays('2026-10-27', '2026-10-20')).toBe(0)
    expect(countWorkingDays('', '2026-10-20')).toBe(0)
  })
})

describe('renderMarkdown', () => {
  it('escapes HTML', () => {
    const html = renderMarkdown('<script>alert(1)</script> **bold** <img src=x onerror=alert(1)>')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
    expect(html).toContain('<strong>bold</strong>')
  })

  it('only allows safe links', () => {
    expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('href')
    expect(renderMarkdown('[x](https://example.com)')).toContain('href="https://example.com"')
    expect(renderMarkdown('[x](https://e.com/"onmouseover="alert(1))')).not.toContain('"onmouseover')
  })

  it('renders headings and lists', () => {
    const html = renderMarkdown('# Title\n\n- one\n- two\n\n1. first')
    expect(html).toContain('<h2>Title</h2>')
    expect(html).toContain('<ul><li>one</li><li>two</li></ul>')
    expect(html).toContain('<ol><li>first</li></ol>')
  })

  it('escapeHtml escapes quotes', () => {
    expect(escapeHtml(`"'<>&`)).toBe('&quot;&#39;&lt;&gt;&amp;')
  })
})

describe('renderChat', () => {
  it('escapes HTML and keeps line breaks', () => {
    const html = renderChat('<img src=x onerror=alert(1)>\n**fett** ~~weg~~')
    expect(html).not.toContain('<img')
    expect(html).toContain('<br>')
    expect(html).toContain('<strong>fett</strong>')
    expect(html).toContain('<s>weg</s>')
  })

  it('formats code blocks, links and mentions', () => {
    const html = renderChat('Hallo @Anna Beispiel, siehe https://intranet.example/x.\n```\n<b>code</b>\n```', ['Anna Beispiel'])
    expect(html).toContain('<span class="mention">@Anna Beispiel</span>')
    expect(html).toContain('<a href="https://intranet.example/x"')
    expect(html).toContain('<pre><code>&lt;b&gt;code&lt;/b&gt;</code></pre>')
  })
})

describe('slash commands', () => {
  it('suggests commands while typing', () => {
    expect(slashMatches('/umf').map((c) => c.name)).toEqual(['umfrage'])
    expect(slashMatches('/poll').map((c) => c.name)).toEqual(['umfrage'])
    expect(slashMatches('hallo /umf')).toEqual([])
  })

  it('reads the command and the rest', () => {
    expect(parseSlash('/status Beim Kunden')).toMatchObject({ command: { name: 'status' }, rest: 'Beim Kunden' })
    expect(parseSlash('/dnd')?.command.name).toBe('nichtstoeren')
    expect(parseSlash('/gibtsnicht')).toBeNull()
  })
})
