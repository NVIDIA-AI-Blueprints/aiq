// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import React from 'react'
import { Document, Page, Text, View, StyleSheet, Font, Link } from '@react-pdf/renderer'
import { marked } from 'marked'

type Token = ReturnType<typeof marked.lexer>[number]
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

function renderParagraph(token: ParagraphToken, index: number): React.ReactNode {
  return (
    <Text key={index} style={styles.paragraph}>
      {parseInlineFormatting(token.text)}
    </Text>
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

    const mainText = textTokens.length
      ? textTokens
          .map((t: any) => {
            if ('text' in t) {
              return stripHtml(t.text as string)
            }
            if ('raw' in t) {
              return stripHtml(t.raw as string)
            }
            return ''
          })
          .join(' ')
      : stripHtml(item.text)

    const hasNestedContent = nestedLists.length > 0

    return (
      <View
        key={`${index}-${itemIndex}`}
        style={hasNestedContent ? styles.listItemWithNested : styles.listItem}
        wrap={!hasNestedContent}
      >
        <Text style={styles.listItemBullet}>{bullet}</Text>
        <View style={styles.listItemText}>
          <Text>{parseInlineFormatting(mainText)}</Text>
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

function parseInlineFormatting(text: string): React.ReactNode {
  text = stripHtml(text)

  const parts: React.ReactNode[] = []
  // Combined regex for links, bold, and italic
  // Links: [text](url) | Bold: **text** or __text__ | Italic: *text* or _text_
  const inlineRegex = /(\[([^\]]+)\]\(([^)]+)\)|\*\*(.+?)\*\*|\*(.+?)\*|__(.+?)__|_(.+?)_)/g
  let key = 0
  let lastIndex = 0
  let match

  while ((match = inlineRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<Text key={`text-${key++}`}>{text.substring(lastIndex, match.index)}</Text>)
    }

    const fullMatch = match[0]

    // Check if it's a link [text](url)
    if (fullMatch.startsWith('[') && match[2] && match[3]) {
      const linkText = match[2]
      const linkUrl = match[3]
      parts.push(
        <Link key={`link-${key++}`} src={linkUrl} style={styles.link}>
          {linkText}
        </Link>
      )
    }
    // Check if it's bold
    else if (fullMatch.startsWith('**') || fullMatch.startsWith('__')) {
      const content = match[4] || match[6]
      parts.push(
        <Text key={`bold-${key++}`} style={{ fontWeight: 'bold' }}>
          {content}
        </Text>
      )
    }
    // It's italic
    else {
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
