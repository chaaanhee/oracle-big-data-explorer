import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { go, openTable } from '../nav'
import { errorText, fmtInt } from '../format'
import type { ErdGraph } from '../types'
import ErdCanvas from './ErdCanvas'

export default function SchemaMap({ owner, focus }: { owner?: string; focus?: string }) {
  const owners = useQuery({ queryKey: ['owners', false], queryFn: () => api.owners(false) })
  const refs = useQuery({ queryKey: ['owner-references'], queryFn: api.ownerReferences })
  const [relatedOnly, setRelatedOnly] = useState(true)
  const [keysOnly, setKeysOnly] = useState(false)
  const [depth, setDepth] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    if (!owner && owners.data?.length) {
      const first = owners.data.find((o) => o.tables > 0) ?? owners.data[0]
      go({ view: 'map', owner: first.owner }, true)
    }
  }, [owner, owners.data])

  useEffect(() => setSelected(focus && owner ? `${owner}.${focus}` : null), [owner, focus])

  const erd = useQuery({
    queryKey: ['erd', owner, relatedOnly],
    queryFn: () => api.erd(owner!, relatedOnly, 150),
    enabled: !!owner && !focus,
  })
  const hood = useQuery({
    queryKey: ['neighborhood', owner, focus, depth],
    queryFn: () => api.neighborhood(owner!, focus!, depth),
    enabled: !!owner && !!focus,
  })
  const q = focus ? hood : erd
  const graph: ErdGraph | undefined = q.data
  const node = graph?.nodes.find((n) => n.id === selected)
  const outgoing = graph?.edges.filter((e) => e.source === selected) ?? []
  const incoming = graph?.edges.filter((e) => e.target === selected) ?? []

  return (
    <div className="map-view">
      <header className="topbar">
        <div className="topbar-title">
          <h1>스키마 맵</h1>
          {focus ? (
            <span className="muted">
              <strong>{owner}.{focus}</strong> 중심 관계 ·{' '}
              <button className="link" onClick={() => go({ view: 'map', owner })}>{owner} 전체 ERD 로</button>
            </span>
          ) : (
            <span className="muted">PK·FK 관계로 그린 ERD — 노드 클릭: 관계 강조, 더블클릭: 테이블 열기</span>
          )}
        </div>
        <div className="row gap-sm">
          <select value={owner ?? ''} onChange={(e) => go({ view: 'map', owner: e.target.value })}>
            {owners.data?.map((o) => (
              <option key={o.owner} value={o.owner}>{o.owner} ({o.tables})</option>
            ))}
          </select>
          {focus ? (
            <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
              <option value={1}>1단계 관계</option>
              <option value={2}>2단계 관계</option>
              <option value={3}>3단계 관계</option>
            </select>
          ) : (
            <label className="check">
              <input type="checkbox" checked={relatedOnly} onChange={(e) => setRelatedOnly(e.target.checked)} />
              관계 있는 테이블만
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={keysOnly} onChange={(e) => setKeysOnly(e.target.checked)} />
            키 컬럼만
          </label>
        </div>
      </header>

      <div className="map-body">
        <div className="map-canvas">
          {q.isLoading && <div className="empty">ERD 를 그리는 중…</div>}
          {q.error && <div className="notice err">{errorText(q.error)}</div>}
          {graph && graph.nodes.length === 0 && (
            <div className="empty">
              <h2>표시할 테이블이 없습니다</h2>
              <p>
                {relatedOnly ? 'FK 관계가 있는 테이블이 없습니다. "관계 있는 테이블만" 을 끄면 모든 테이블을 볼 수 있습니다.' : '테이블이 없습니다.'}
              </p>
            </div>
          )}
          {graph && graph.nodes.length > 0 && (
            <ErdCanvas
              graph={graph}
              keysOnly={keysOnly}
              selected={selected}
              onSelect={setSelected}
              onOpen={(n) => openTable(n.owner, n.name, 'structure')}
            />
          )}
          {graph && (
            <div className="map-legend">
              <span><i className="lg-line" /> FK (같은 Owner)</span>
              <span><i className="lg-line cross" /> Owner 간 FK</span>
              <span><i className="lg-box ext" /> 다른 Owner 테이블</span>
              <span className="muted">
                노드 {graph.nodes.length} · 관계 {graph.edges.length}
                {graph.unrelated_tables ? ` · FK 없는 테이블 ${graph.unrelated_tables}개 ${relatedOnly ? '숨김' : ''}` : ''}
                {graph.truncated ? ' · 일부만 표시' : ''}
              </span>
            </div>
          )}
        </div>

        <aside className="map-side">
          {node ? (
            <>
              <div className="row gap-sm">
                <h3>{node.owner}.{node.name}</h3>
              </div>
              {node.comment && <div className="muted small">{node.comment}</div>}
              <div className="muted small">
                {node.type === 'VIEW' ? '뷰' : `통계상 ${fmtInt(node.num_rows)}행`} · 컬럼 {node.column_count}개
              </div>
              <div className="row gap-sm wrap" style={{ margin: '10px 0' }}>
                <button className="btn sm primary" onClick={() => openTable(node.owner, node.name)}>데이터 보기</button>
                <button className="btn sm" onClick={() => openTable(node.owner, node.name, 'structure')}>구조</button>
                {!(focus && `${owner}.${focus}` === node.id) && (
                  <button className="btn sm" onClick={() => go({ view: 'map', owner: node.owner, focus: node.name })}>
                    이 테이블 중심으로
                  </button>
                )}
              </div>
              <h4>참조 (→ 부모)</h4>
              {outgoing.length === 0 && <div className="muted small">없음</div>}
              {outgoing.map((e) => (
                <div key={e.id} className="rel-item" onClick={() => setSelected(e.target)}>
                  <strong>{e.target}</strong>
                  {e.cross_owner && <span className="badge sm badge-cross">Owner 간</span>}
                  <div className="muted small mono">{e.from_columns.join(', ')} → {e.to_columns.join(', ')}</div>
                </div>
              ))}
              <h4>참조됨 (← 자식)</h4>
              {incoming.length === 0 && <div className="muted small">없음</div>}
              {incoming.map((e) => (
                <div key={e.id} className="rel-item" onClick={() => setSelected(e.source)}>
                  <strong>{e.source}</strong>
                  {e.cross_owner && <span className="badge sm badge-cross">Owner 간</span>}
                  <div className="muted small mono">{e.from_columns.join(', ')} → {e.to_columns.join(', ')}</div>
                </div>
              ))}
              <h4>컬럼</h4>
              <table className="grid compact">
                <tbody>
                  {node.columns.map((c) => (
                    <tr key={c.name} title={c.comment ?? undefined}>
                      <td>
                        {c.pk && <span className="key pk">PK</span>}
                        {c.fk && <span className="key fk">FK</span>}
                        {c.name}
                      </td>
                      <td className="mono small muted">{c.type}{c.nullable ? '' : ' NN'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <>
              <h3>Owner 간 참조 관계</h3>
              <div className="muted small" style={{ marginBottom: 8 }}>다른 Owner 의 테이블을 참조하는 외래키</div>
              {refs.data?.length === 0 && <div className="muted">없음</div>}
              {refs.data?.map((r) => (
                <div
                  key={`${r.from_owner}>${r.to_owner}`}
                  className={`rel-item ${r.from_owner === owner || r.to_owner === owner ? 'hl' : ''}`}
                  onClick={() => go({ view: 'map', owner: r.from_owner })}
                >
                  <div>
                    <strong>{r.from_owner}</strong> → <strong>{r.to_owner}</strong>
                    <span className="badge sm">{r.fk_count} FK</span>
                  </div>
                  {r.examples.map((x) => (
                    <div key={x} className="muted small mono">{x}</div>
                  ))}
                </div>
              ))}
              <div className="hint" style={{ marginTop: 16 }}>테이블을 클릭하면 상세 정보와 관계가 여기에 표시됩니다.</div>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
