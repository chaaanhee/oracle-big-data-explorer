import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { go, openTable } from '../nav'
import { errorText } from '../format'
import type { RelatedTable, TableDetail } from '../types'
import ErdCanvas from './ErdCanvas'

const DIRECTION: Record<RelatedTable['direction'], string> = {
  references: '참조함 →',
  referenced_by: '← 참조됨',
  maybe_references: '참조 추정 →',
  maybe_referenced_by: '← 참조됨 추정',
}

export default function RelationsPanel({ detail }: { detail: TableDetail }) {
  const { owner, name } = detail
  const [depth, setDepth] = useState(1)
  const [keysOnly, setKeysOnly] = useState(true)
  const [selected, setSelected] = useState<string | null>(`${owner}.${name}`)
  const hood = useQuery({
    queryKey: ['neighborhood', owner, name, depth],
    queryFn: () => api.neighborhood(owner, name, depth),
  })
  const related = useQuery({ queryKey: ['related', owner, name], queryFn: () => api.related(owner, name) })

  return (
    <div className="relations">
      <div className="rel-graph">
        <div className="toolbar">
          <strong>관계 ERD</strong>
          <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
            <option value={1}>1단계</option>
            <option value={2}>2단계</option>
            <option value={3}>3단계</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={keysOnly} onChange={(e) => setKeysOnly(e.target.checked)} />
            키 컬럼만
          </label>
          <span className="spacer" />
          <button className="btn sm" onClick={() => go({ view: 'map', owner, focus: name })}>스키마 맵에서 크게 보기</button>
        </div>
        <div className="map-canvas small-canvas">
          {hood.error && <div className="notice err">{errorText(hood.error)}</div>}
          {hood.data && hood.data.edges.length === 0 && (
            <div className="empty small">
              <h2>FK 관계가 없습니다</h2>
              <p>오른쪽의 추정 관계·유사 이름 테이블을 확인해 보세요.</p>
            </div>
          )}
          {hood.data && hood.data.edges.length > 0 && (
            <ErdCanvas
              graph={hood.data}
              keysOnly={keysOnly}
              selected={selected}
              onSelect={setSelected}
              onOpen={(n) => openTable(n.owner, n.name, 'relations')}
            />
          )}
        </div>
      </div>

      <aside className="rel-side scroll">
        {related.error && <div className="notice err">{errorText(related.error)}</div>}
        <h3>FK 로 연결된 테이블</h3>
        <RelatedList items={related.data?.foreign_keys} empty="선언된 외래키가 없습니다." />

        <h3>추정 관계 <span className="muted small">(FK 없이 키 컬럼명이 같음)</span></h3>
        <RelatedList items={related.data?.implicit} empty="추정되는 관계가 없습니다." />

        <h3>이름이 비슷한 테이블</h3>
        {related.data?.similar.length === 0 && <div className="muted small">없음</div>}
        {related.data?.similar.map((s) => (
          <div key={`${s.owner}.${s.name}`} className="rel-item" onClick={() => openTable(s.owner, s.name)}>
            <div className="row gap-sm">
              <span className="muted">{s.owner}.</span>
              <strong>{s.name}</strong>
              <span className="spacer" />
              <span className="score" style={{ ['--s' as string]: s.score }}>{Math.round(s.score * 100)}%</span>
            </div>
          </div>
        ))}
      </aside>
    </div>
  )
}

function RelatedList({ items, empty }: { items?: RelatedTable[]; empty: string }) {
  if (!items) return <div className="muted small">불러오는 중…</div>
  if (items.length === 0) return <div className="muted small">{empty}</div>
  return (
    <>
      {items.map((r, i) => (
        <div key={`${r.owner}.${r.name}.${r.direction}.${i}`} className="rel-item" onClick={() => openTable(r.owner, r.name, 'relations')}>
          <div className="row gap-sm">
            <span className={`dir dir-${r.direction}`}>{DIRECTION[r.direction]}</span>
            <span className="muted">{r.owner}.</span>
            <strong>{r.name}</strong>
          </div>
          <div className="muted small mono">{r.via}{r.constraint ? ` · ${r.constraint}` : ''}</div>
        </div>
      ))}
    </>
  )
}
