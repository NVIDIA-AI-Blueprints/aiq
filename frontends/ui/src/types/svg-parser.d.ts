declare module 'svg-parser' {
  export interface SvgTextNode {
    type: 'text'
    value: string
  }

  export interface SvgElementNode {
    type: 'element'
    tagName: string
    properties: Record<string, string>
    children: Array<SvgElementNode | SvgTextNode>
  }

  export interface SvgRootNode {
    type: 'root'
    children: Array<SvgElementNode | SvgTextNode>
  }

  export type SvgNode = SvgRootNode | SvgElementNode | SvgTextNode

  export function parse(input: string): SvgRootNode
}
