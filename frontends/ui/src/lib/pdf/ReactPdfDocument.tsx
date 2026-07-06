// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import React from 'react'
import { Document, Page, Text, View, StyleSheet, Font, Link, Image } from '@react-pdf/renderer'
import { marked } from 'marked'

type Token = ReturnType<typeof marked.lexer>[number]
type ImageToken = { type: 'image'; href: string; text?: string; title?: string }
type HeadingToken = Extract<Token, { type: 'heading' }>
type ParagraphToken = Extract<Token, { type: 'paragraph' }>
type ListToken = Extract<Token, { type: 'list' }>
type TableToken = Extract<Token, { type: 'table' }>
type CodeToken = Extract<Token, { type: 'code' }>
type BlockquoteToken = Extract<Token, { type: 'blockquote' }>
type HtmlToken = Extract<Token, { type: 'html' }>

Font.register({
  family: 'Helvetica',
  fonts: [{ src: 'Helvetica' }, { src: 'Helvetica-Bold', fontWeight: 'bold' }],
})

// Disable hyphenation — react-pdf's default English hyphenation inserts
// hyphens into long words (including URLs), making them unusable when copied.
Font.registerHyphenationCallback((word) => [word])

const styles = StyleSheet.create({
  page: {
    padding: 56.69,
    fontFamily: 'Helvetica',
    fontSize: 10,
    lineHeight: 1.5,
  },
  h1: {
    fontSize: 18,
    fontWeight: 'bold',
    marginTop: 16,
    marginBottom: 12,
    lineHeight: 1.2,
  },
  h2: {
    fontSize: 14,
    fontWeight: 'bold',
    marginTop: 14,
    marginBottom: 8,
    lineHeight: 1.3,
  },
  h3: {
    fontSize: 12,
    fontWeight: 'bold',
    marginTop: 12,
    marginBottom: 6,
    lineHeight: 1.4,
  },
  paragraph: {
    marginBottom: 8,
    textAlign: 'left',
  },
  listItem: {
    flexDirection: 'row',
    marginBottom: 4,
  },
  listItemWithNested: {
    flexDirection: 'row',
    marginBottom: 4,
  },
  listItemBullet: {
    width: 20,
    marginRight: 5,
    flexShrink: 0,
  },
  listItemText: {
    flex: 1,
    flexDirection: 'column',
  },
  table: {
    marginTop: 10,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#000000',
  },
  tableRow: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: '#000000',
    minHeight: 30,
  },
  tableHeaderRow: {
    flexDirection: 'row',
    backgroundColor: '#f2f2f2',
    borderBottomWidth: 1,
    borderBottomColor: '#000000',
    minHeight: 30,
  },
  tableCell: {
    flex: 1,
    padding: 8,
    borderRightWidth: 1,
    borderRightColor: '#000000',
    justifyContent: 'center',
  },
  tableCellLast: {
    flex: 1,
    padding: 8,
    justifyContent: 'center',
  },
  tableHeaderCell: {
    fontWeight: 'bold',
  },
  codeBlock: {
    backgroundColor: '#f5f5f5',
    border: '1px solid #cccccc',
    padding: 10,
    marginTop: 10,
    marginBottom: 10,
    fontFamily: 'Courier',
    fontSize: 9,
  },
  preBlock: {
    fontFamily: 'Courier',
    fontSize: 9,
    marginTop: 8,
    marginBottom: 8,
  },
  blockquote: {
    borderLeftWidth: 3,
    borderLeftColor: '#cccccc',
    paddingLeft: 10,
    marginLeft: 10,
    marginTop: 8,
    marginBottom: 8,
    fontStyle: 'italic',
  },
  hr: {
    borderBottomWidth: 1,
    borderBottomColor: '#cccccc',
    marginTop: 10,
    marginBottom: 10,
  },
  link: {
    color: '#0066cc',
    textDecoration: 'underline',
  },
  figure: {
    marginTop: 10,
    marginBottom: 10,
    alignItems: 'center',
  },
  image: {
    // Explicit width is required: react-pdf renders an Image at intrinsic pixel size when
    // width is unset, so a large chart overflows the page. '100%' fits the parent and scales
    // height by aspect ratio.
    width: '100%',
    objectFit: 'contain',
  },
  imageCaption: {
    fontSize: 9,
    color: '#555555',
    marginTop: 4,
    textAlign: 'center',
    fontStyle: 'italic',
  },
})

interface MarkdownPDFProps {
  markdown: string
}

export const MarkdownPDF: React.FC<MarkdownPDFProps> = ({ markdown }) => {
  const tokens = marked.lexer(markdown)

  return (
    <Document>
      <Page size="A4" style={styles.page}>
        {tokens.map((token, index) => renderToken(token, index))}
      </Page>
    </Document>
  )
}

function renderToken(token: Token, index: number): React.ReactNode {
  switch (token.type) {
    case 'heading':
      return renderHeading(token as HeadingToken, index)
    case 'paragraph':
      return renderParagraph(token as ParagraphToken, index)
    case 'list':
      return renderList(token as ListToken, index)
    case 'table':
      return renderTable(token as TableToken, index)
    case 'code':
      return renderCode(token as CodeToken, index)
    case 'blockquote':
      return renderBlockquote(token as BlockquoteToken, index)
    case 'hr':
      return <View key={index} style={styles.hr} />
    case 'html':
      return renderHtml(token as HtmlToken, index)
    case 'space':
      return null
    default:
      return null
  }
}

function renderHeading(token: HeadingToken, index: number): React.ReactNode {
  const styleMap: Record<number, typeof styles.h1> = {
    1: styles.h1,
    2: styles.h2,
    3: styles.h3,
  }

  return (
    <Text key={index} style={styleMap[token.depth] || styles.h3}>
      {parseInlineFormatting(token.text)}
    </Text>
  )
}

// Matches markdown image syntax so it can be stripped from inline text (the image is rendered
// as a block figure instead of leaking through the inline link parser as a stray link).
const IMAGE_MD_RE = /!\[[^\]]*\]\([^)]*\)/g

// Only embed raster image data URIs within a bounded decoded size — the markdown may carry an
// arbitrary `data:` URI (e.g. one the report wrote directly), which we must not feed unchecked
// into the PDF renderer.
const MAX_PDF_EMBED_BYTES = 8 * 1024 * 1024
// @react-pdf/renderer supports PNG and JPEG only; a WebP data URI would pass the size
// guard and then fail silently during PDF rendering, so it is excluded here.
const DATA_IMAGE_RE = /^data:image\/(?:png|jpe?g);base64,([A-Za-z0-9+/=]+)$/

function isEmbeddableDataImage(href: string): boolean {
  const match = DATA_IMAGE_RE.exec(href)
  if (!match) return false
  const b64 = match[1]
  const padding = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0
  const decodedBytes = Math.floor((b64.length * 3) / 4) - padding
  return decodedBytes <= MAX_PDF_EMBED_BYTES
}

/**
 * Recursively collect embeddable image tokens. Only bounded raster `data:` URIs are embeddable
 * (artifact refs are pre-resolved to data URIs server-side); remote/unresolved/oversized images
 * are skipped so the PDF never shows a broken figure or blows up memory. Walks nested `tokens`
 * so images inside list items, blockquotes, etc. are found, not just top-level paragraphs.
 */
function collectEmbeddableImages(tokens: unknown): ImageToken[] {
  if (!Array.isArray(tokens)) return []
  const found: ImageToken[] = []
  for (const token of tokens) {
    const t = token as { type?: string; href?: string; tokens?: unknown }
    if (t.type === 'image' && typeof t.href === 'string' && isEmbeddableDataImage(t.href)) {
      found.push(t as ImageToken)
    } else if (Array.isArray(t.tokens)) {
      found.push(...collectEmbeddableImages(t.tokens))
    }
  }
  return found
}

/** Render embeddable images as centered block figures with optional captions. */
function renderFigures(images: ImageToken[], keyPrefix: string): React.ReactNode[] {
  return images.map((img, imgIndex) => (
    <View key={`${keyPrefix}-img-${imgIndex}`} style={styles.figure} wrap={false}>
      <Image src={img.href} style={styles.image} />
      {(img.text || img.title) && <Text style={styles.imageCaption}>{img.text || img.title}</Text>}
    </View>
  ))
}

function renderParagraph(token: ParagraphToken, index: number): React.ReactNode {
  const images = collectEmbeddableImages((token as ParagraphToken & { tokens?: Token[] }).tokens)
  // Strip image markdown so a standalone `![alt](data:...)` does not also render as a link.
  const textWithoutImages = token.text.replace(IMAGE_MD_RE, '').trim()

  if (images.length === 0) {
    if (!textWithoutImages) return null
    return (
      <Text key={index} style={styles.paragraph}>
        {parseInlineFormatting(textWithoutImages)}
      </Text>
    )
  }

  return (
    <View key={index}>
      {textWithoutImages && (
        <Text style={styles.paragraph}>{parseInlineFormatting(textWithoutImages)}</Text>
      )}
      {renderFigures(images, String(index))}
    </View>
  )
}

function renderList(token: ListToken, index: number, _nested: boolean = false): React.ReactNode {
  return token.items.map((item: any, itemIndex: number) => {
    const bullet = token.ordered ? `${itemIndex + 1}.` : '•'
    const textTokens: Token[] = []
    const nestedLists: Token[] = []

    if (item.tokens?.length) {
      item.tokens.forEach((t: Token) => {
        if (t.type === 'list') {
          nestedLists.push(t)
        } else {
          textTokens.push(t)
        }
      })
    }

    const rawText = textTokens.length
      ? textTokens
          .map((t: any) => {
            if ('text' in t) {
              return stripHtml(preserveHtmlLinks(t.text as string))
            }
            if ('raw' in t) {
              return stripHtml(preserveHtmlLinks(t.raw as string))
            }
            return ''
          })
          .join(' ')
      : stripHtml(preserveHtmlLinks(item.text))

    // A bullet may carry an embedded figure (e.g. "- The chart: ![alt](data:...)"). Collect
    // only from this item's own text tokens (not nestedLists, which render their own images)
    // so images in nested list items aren't rendered twice.
    const images = collectEmbeddableImages(textTokens)
    const mainText = rawText.replace(IMAGE_MD_RE, '').trim()
    const hasNestedContent = nestedLists.length > 0 || images.length > 0

    return (
      <View
        key={`${index}-${itemIndex}`}
        style={hasNestedContent ? styles.listItemWithNested : styles.listItem}
        wrap={!hasNestedContent}
      >
        <Text style={styles.listItemBullet}>{bullet}</Text>
        <View style={styles.listItemText}>
          {mainText && <Text>{parseInlineFormatting(mainText)}</Text>}
          {renderFigures(images, `${index}-${itemIndex}`)}
          {nestedLists.map((nestedList: any, nlIndex: number) =>
            renderList(nestedList as ListToken, nlIndex, true)
          )}
        </View>
      </View>
    )
  })
}

function renderTable(token: TableToken, index: number): React.ReactNode {
  const getCellText = (cell: unknown): string => {
    if (typeof cell === 'string') {
      return cell
    }
    if (cell && typeof cell === 'object' && 'text' in cell) {
      return (
        (cell as { text?: string; raw?: string }).text ||
        (cell as { text?: string; raw?: string }).raw ||
        String(cell)
      )
    }
    return ''
  }

  const isSmallTable = token.rows.length <= 3

  return (
    <View key={index} style={styles.table} wrap={!isSmallTable}>
      <View style={styles.tableHeaderRow} wrap={false}>
        {token.header.map((cell: any, cellIndex: number) => {
          const isLast = cellIndex === token.header.length - 1
          return (
            <View key={cellIndex} style={isLast ? styles.tableCellLast : styles.tableCell}>
              <Text style={styles.tableHeaderCell}>{parseInlineFormatting(getCellText(cell))}</Text>
            </View>
          )
        })}
      </View>

      {token.rows.map((row: any[], rowIndex: number) => (
        <View key={rowIndex} style={styles.tableRow} wrap={false}>
          {row.map((cell: any, cellIndex: number) => {
            const isLast = cellIndex === row.length - 1
            return (
              <View key={cellIndex} style={isLast ? styles.tableCellLast : styles.tableCell}>
                <Text>{parseInlineFormatting(getCellText(cell))}</Text>
              </View>
            )
          })}
        </View>
      ))}
    </View>
  )
}

function renderCode(token: CodeToken, index: number): React.ReactNode {
  const lineCount = token.text.split('\n').length
  const isSmallCodeBlock = lineCount <= 5

  return (
    <View key={index} style={styles.codeBlock} wrap={!isSmallCodeBlock}>
      <Text>{token.text}</Text>
    </View>
  )
}

function renderBlockquote(token: BlockquoteToken, index: number): React.ReactNode {
  return (
    <View key={index} style={styles.blockquote}>
      {token.tokens.map((subToken: Token, subIndex: number) => renderToken(subToken, subIndex))}
    </View>
  )
}

function renderHtml(token: HtmlToken, index: number): React.ReactNode {
  const preMatch = token.raw?.match(/<pre>([\s\S]*?)<\/pre>/i)

  if (preMatch) {
    const content = preMatch[1].trim()
    const lineCount = content.split('\n').length
    const charCount = content.length
    const isSmall = lineCount <= 5 && charCount <= 500

    return (
      <Text key={index} style={styles.preBlock} wrap={!isSmall}>
        {content}
      </Text>
    )
  }

  return null
}

function stripHtml(text: string): string {
  return text.replace(/<[^>]*>/g, '')
}

/** Convert HTML <a> tags to markdown link syntax so they survive stripHtml. */
function preserveHtmlLinks(text: string): string {
  return text.replace(/<a\s[^>]*href=["']([^"']*)["'][^>]*>(.*?)<\/a>/gi, '[$2]($1)')
}

function parseInlineFormatting(text: string): React.ReactNode {
  text = preserveHtmlLinks(text)
  text = stripHtml(text)

  const parts: React.ReactNode[] = []
  // Links: [text](url) — supports balanced parens in URLs (e.g. Wikipedia)
  // Bold: **text** or __text__ | Italic: *text* or _text_
  const inlineRegex =
    /(\[([^\]]+)\]\(((?:[^()\s]|\([^)]*\))+)\)|\*\*(.+?)\*\*|\*(.+?)\*|__(.+?)__|_(.+?)_)/g
  let key = 0
  let lastIndex = 0
  let match

  while ((match = inlineRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<Text key={`text-${key++}`}>{text.substring(lastIndex, match.index)}</Text>)
    }

    const fullMatch = match[0]

    if (fullMatch.startsWith('[') && match[2] && match[3]) {
      const linkText = match[2]
      const linkUrl = match[3]

      if (linkUrl.startsWith('#')) {
        // Anchor links have no destination in a PDF — render as styled text
        parts.push(
          <Text key={`anchor-${key++}`} style={{ fontWeight: 'bold' }}>
            {linkText}
          </Text>
        )
      } else {
        parts.push(
          <Link key={`link-${key++}`} src={linkUrl} style={styles.link}>
            {linkText}
          </Link>
        )
      }
    } else if (fullMatch.startsWith('**') || fullMatch.startsWith('__')) {
      const content = match[4] || match[6]
      parts.push(
        <Text key={`bold-${key++}`} style={{ fontWeight: 'bold' }}>
          {content}
        </Text>
      )
    } else {
      const content = match[5] || match[7]
      parts.push(
        <Text key={`italic-${key++}`} style={{ fontStyle: 'italic' }}>
          {content}
        </Text>
      )
    }

    lastIndex = match.index + fullMatch.length
  }

  if (lastIndex < text.length) {
    parts.push(<Text key={`text-${key++}`}>{text.substring(lastIndex)}</Text>)
  }

  return parts.length > 0 ? parts : text
}
