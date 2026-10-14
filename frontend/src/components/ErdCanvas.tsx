import { memo, useEffect, useMemo } from 'react'
import {
  Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps,
} from '@xyflow/react'
import dagre from '@dagrejs/dagre'
import '@xyflow/react/dist/style.css'
import { fmtInt } from '../format'
import type { ErdColumn, ErdEdge, ErdGraph, ErdNode } from '../types'

const NODE_W = 250
const HEAD_H = 44
const ROW_H = 20

type TableNodeData = {
  table: ErdNode
  columns: ErdColumn[]
  hidden: number
  center: boolean
  selected: boolean
  dim: boolean
}
type TableNode = Node<TableNodeData, 'table'>

const TableNodeView = memo(function TableNodeView({ data }: NodeProps<TableNode>) {
  const { table, columns, hidden, center, selected, dim } = data
  return (
    <div
      className={`erd-node ${table.external ? 'external' : ''} ${center ? 'center' : ''} ${selected ? 'sel' : ''} ${dim ? 'dim' : ''}`}
      style={{ width: NODE_W }}
    >
      <Handle type="target" position={Position.Left} id="tbl-t" className="erd-handle" style={{ top: HEAD_H / 2 }} />
      <Handle type="source" position={Position.Right} id="tbl-s" className="erd-handle" style={{ top: HEAD_H / 2 }} />
      <div className="erd-head" title={table.comment ?? undefined}>
        <div className="erd-title">
          {table.external && <span className="erd-owner">{table.owner}.</span>}
          {table.name}
        </div>
        <div className="erd-sub">
          {table.type === 'VIEW' ? '뷰' : table.num_rows !== null ? `${fmtInt(table.num_rows)}행` : '통계 없음'}
          {table.comment ? ` · ${table.comment}` : ''}
        </div>
      </div>
      {columns.map((c) => (
        <div key={c.name} className="erd-col" title={[c.type, c.comment].filter(Boolean).join(' · ')}>
          <Handle type="target" position={Position.Left} id={`${c.name}-t`} className="erd-handle" />
          <span className="erd-keys">
            {c.pk && <span className="key pk">PK</span>}
            {c.fk && <span className="key fk">FK</span>}
          </span>
          <span className={`erd-cname ${c.nullable ? '' : 'nn'}`}>{c.name}</span>
          <span className="erd-ctype">{c.type}</span>
          <Handle type="source" position={Position.Right} id={`${c.name}-s`} className="erd-handle" />
        </div>
      ))}
      {hidden > 0 && <div className="erd-more">… 컬럼 {hidden}개 더</div>}
    </div>
  )
})

const nodeTypes = { table: TableNodeView }

export interface ErdProps {
  graph: ErdGraph
  keysOnly: boolean
  selected: string | null
  onSelect: (id: string | null) => void
  onOpen: (node: ErdNode) => void
}

function visibleColumns(n: ErdNode, keysOnly: boolean) {
  const cols = keysOnly ? n.columns.filter((c) => c.pk || c.fk) : n.columns
  return { cols, hidden: n.column_count - cols.length }
}

function nodeHeight(n: ErdNode, keysOnly: boolean) {
  const { cols, hidden } = visibleColumns(n, keysOnly)
  return HEAD_H + cols.length * ROW_H + (hidden > 0 ? ROW_H : 0) + 6
}

function layout(graph: ErdGraph, keysOnly: boolean) {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 90, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  const sizes = new Map<string, number>()
  for (const n of graph.nodes) {
    const h = nodeHeight(n, keysOnly)
    sizes.set(n.id, h)
    g.setNode(n.id, { width: NODE_W, height: h })
  }
  for (const e of graph.edges) {
    if (e.source !== e.target) g.setEdge(e.source, e.target)
  }
  dagre.layout(g)
  const pos = new Map<string, { x: number; y: number }>()
  for (const n of graph.nodes) {
    const p = g.node(n.id)
    pos.set(n.id, { x: p.x - NODE_W / 2, y: p.y - (sizes.get(n.id) ?? 0) / 2 })
  }
  return pos
}

function Canvas({ graph, keysOnly, selected, onSelect, onOpen }: ErdProps) {
  const positions = useMemo(() => layout(graph, keysOnly), [graph, keysOnly])
  const { fitView } = useReactFlow()

  const neighbors = useMemo(() => {
    if (!selected) return null
    const s = new Set([selected])
    for (const e of graph.edges) {
      if (e.source === selected) s.add(e.target)
      if (e.target === selected) s.add(e.source)
    }
    return s
  }, [graph.edges, selected])

  const nodes: TableNode[] = useMemo(
    () =>
      graph.nodes.map((n) => {
        const { cols, hidden } = visibleColumns(n, keysOnly)
        return {
          id: n.id,
          type: 'table',
          position: positions.get(n.id) ?? { x: 0, y: 0 },
          width: NODE_W,
          height: nodeHeight(n, keysOnly),
          data: {
            table: n, columns: cols, hidden,
            center: graph.center === n.id,
            selected: selected === n.id,
            dim: !!neighbors && !neighbors.has(n.id),
          },
        }
      }),
    [graph, keysOnly, positions, selected, neighbors],
  )

  const edges: Edge[] = useMemo(() => {
    const colSet = new Map(graph.nodes.map((n) => [n.id, new Set(visibleColumns(n, keysOnly).cols.map((c) => c.name))]))
    return graph.edges.map((e: ErdEdge) => {
      const sc = e.from_columns[0]
      const tc = e.to_columns[0]
      const active = !!selected && (e.source === selected || e.target === selected)
      const color = e.cross_owner ? '#e07b00' : active ? '#4f5dff' : '#98a1b5'
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: colSet.get(e.source)?.has(sc) ? `${sc}-s` : 'tbl-s',
        targetHandle: colSet.get(e.target)?.has(tc) ? `${tc}-t` : 'tbl-t',
        type: 'smoothstep',
        animated: active,
        label: active ? `${e.name}` : undefined,
        labelStyle: { fontSize: 10, fill: '#4b5265' },
        labelBgStyle: { fill: '#fff' },
        style: {
          stroke: color,
          strokeWidth: active ? 2 : 1.3,
          strokeDasharray: e.cross_owner ? '6 4' : undefined,
          opacity: selected && !active ? 0.25 : 1,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
      }
    })
  }, [graph, keysOnly, selected])

  useEffect(() => {
    const id = requestAnimationFrame(() => fitView({ padding: 0.15, duration: 300 }))
    return () => cancelAnimationFrame(id)
  }, [graph, keysOnly, fitView])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => onSelect(n.id === selected ? null : n.id)}
      onNodeDoubleClick={(_, n) => onOpen((n as TableNode).data.table)}
      onPaneClick={() => onSelect(null)}
      nodesConnectable={false}
      nodesDraggable={false}
      edgesFocusable={false}
      minZoom={0.1}
      maxZoom={2}
      fitView
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={20} color="#e4e7ee" />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeColor={(n) => ((n as TableNode).data.table.external ? '#f3d9b1' : '#c9cfff')} />
    </ReactFlow>
  )
}

export default function ErdCanvas(props: ErdProps) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  )
}
