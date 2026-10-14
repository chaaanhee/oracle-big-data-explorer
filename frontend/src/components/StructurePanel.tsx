import { openTable } from '../nav'
import { fmtDate } from '../format'
import type { ForeignKey, TableDetail } from '../types'

export default function StructurePanel({ detail }: { detail: TableDetail }) {
  const { columns, primary_key: pk, unique_keys, foreign_keys, referenced_by, indexes } = detail

  return (
    <div className="scroll structure">
      <div className="facts">
        <Fact label="유형" value={detail.type === 'VIEW' ? '뷰' : '테이블'} />
        <Fact label="상태" value={detail.status} warn={detail.status !== 'VALID'} />
        <Fact label="컬럼" value={`${columns.length}개`} />
        <Fact label="생성" value={fmtDate(detail.created)} />
        <Fact label="최근 DDL" value={fmtDate(detail.last_ddl_time)} />
        <Fact label="기본키" value={pk ? pk.columns.join(', ') : '없음'} warn={!pk && detail.type === 'TABLE'} />
      </div>

      <h3 className="section-title">컬럼 정의</h3>
      <table className="grid compact">
        <thead>
          <tr>
            <th className="num">#</th>
            <th>컬럼</th>
            <th>타입</th>
            <th>NULL</th>
            <th>키</th>
            <th>기본값</th>
            <th>설명</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((c) => (
            <tr key={c.name}>
              <td className="num muted">{c.id}</td>
              <td><strong>{c.name}</strong></td>
              <td className="mono">{c.type}</td>
              <td>{c.nullable ? <span className="muted">NULL 허용</span> : <span className="nn-tag">NOT NULL</span>}</td>
              <td>
                {c.pk && <span className="key pk">PK</span>}
                {c.fk?.map((target) => {
                  const [o, t, col] = target.split('.')
                  return (
                    <button key={target} className="link fk-link" onClick={() => openTable(o, t, 'structure')}>
                      <span className="key fk">FK</span> {o}.{t}.{col}
                    </button>
                  )
                })}
              </td>
              <td className="mono muted">{c.default}</td>
              <td className="muted">{c.comment}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {(pk || unique_keys.length > 0) && (
        <>
          <h3 className="section-title">기본키 · 유니크 제약</h3>
          <table className="grid compact">
            <thead>
              <tr><th>제약</th><th>유형</th><th>컬럼</th><th>상태</th></tr>
            </thead>
            <tbody>
              {pk && (
                <tr>
                  <td className="mono">{pk.name}</td><td>PRIMARY KEY</td><td>{pk.columns.join(', ')}</td><td>{pk.status}</td>
                </tr>
              )}
              {unique_keys.map((u) => (
                <tr key={u.name}>
                  <td className="mono">{u.name}</td><td>UNIQUE</td><td>{u.columns.join(', ')}</td><td>{u.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h3 className="section-title">외래키 — 이 테이블이 참조 ({foreign_keys.length})</h3>
      <FkTable fks={foreign_keys} side="to" />

      <h3 className="section-title">외래키 — 이 테이블을 참조 ({referenced_by.length})</h3>
      <FkTable fks={referenced_by} side="from" />

      {detail.type === 'TABLE' && (
        <>
          <h3 className="section-title">인덱스 ({indexes.length})</h3>
          {indexes.length === 0 ? (
            <div className="muted">인덱스가 없습니다.</div>
          ) : (
            <table className="grid compact">
              <thead>
                <tr><th>인덱스</th><th>유형</th><th>유니크</th><th>컬럼</th><th>상태</th></tr>
              </thead>
              <tbody>
                {indexes.map((ix) => (
                  <tr key={ix.name}>
                    <td className="mono">{ix.owner !== detail.owner ? `${ix.owner}.` : ''}{ix.name}</td>
                    <td>{ix.type}</td>
                    <td>{ix.unique ? 'UNIQUE' : ''}</td>
                    <td>{ix.columns.join(', ')}</td>
                    <td className={ix.status === 'VALID' || ix.status === 'N/A' ? '' : 'bad-text'}>{ix.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {detail.view_text && (
        <>
          <h3 className="section-title">뷰 정의</h3>
          <pre className="code-block">{detail.view_text}</pre>
        </>
      )}
    </div>
  )
}

function Fact({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className={`fact ${warn ? 'warn' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function FkTable({ fks, side }: { fks: ForeignKey[]; side: 'to' | 'from' }) {
  if (fks.length === 0) return <div className="muted">없음</div>
  return (
    <table className="grid compact">
      <thead>
        <tr>
          <th>제약</th>
          <th>{side === 'to' ? '참조 대상 테이블' : '참조하는 테이블'}</th>
          <th>컬럼 매핑</th>
          <th>ON DELETE</th>
          <th>상태</th>
        </tr>
      </thead>
      <tbody>
        {fks.map((f) => {
          const o = side === 'to' ? f.to_owner : f.from_owner
          const t = side === 'to' ? f.to_table : f.from_table
          const cross = f.from_owner !== f.to_owner
          return (
            <tr key={`${f.from_owner}.${f.name}`}>
              <td className="mono">{f.name}</td>
              <td>
                <button className="link" onClick={() => openTable(o, t, 'structure')}>
                  {o}.{t}
                </button>
                {cross && <span className="badge sm badge-cross">Owner 간</span>}
              </td>
              <td className="mono">
                {f.from_columns.map((c, i) => `${c} → ${f.to_columns[i]}`).join(', ')}
              </td>
              <td>{f.delete_rule}</td>
              <td className={f.status === 'ENABLED' ? '' : 'warn-text'}>{f.status}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
