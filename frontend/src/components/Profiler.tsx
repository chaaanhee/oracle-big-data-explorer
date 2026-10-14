import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { daysAgo, errorText, fmtBytes, fmtCell, fmtDate, fmtInt, fmtMs, fmtPct } from '../format'
import type { Info, MetaColumn, ProfileSourceKind, ScanColumn, ScanProfile, TableDetail } from '../types'

export const SOURCE_INFO: Record<ProfileSourceKind, { label: string; desc: string }> = {
  metadata: { label: '메타데이터', desc: '데이터 딕셔너리(객체·세그먼트·변경 이력) — 조회 비용 거의 없음' },
  stats: { label: '기존 통계', desc: '옵티마이저 통계(DBMS_STATS) — 마지막 수집 시점 기준, 현재와 다를 수 있음' },
  sample: { label: '샘플링', desc: '일부 행만 읽어 계산한 근사치 — 고유값 수는 근사 함수 사용' },
  exact: { label: '정확(전체 스캔)', desc: '모든 행을 읽어 계산 — 정확하지만 비용이 큼' },
}

export function SourceBadge({ source }: { source: ProfileSourceKind | null | undefined }) {
  if (!source) return null
  return (
    <span className={`src src-${source}`} title={SOURCE_INFO[source].desc}>
      {SOURCE_INFO[source].label}
    </span>
  )
}

const LEVEL_ICON = { ok: '✔', info: 'ℹ', warn: '!', bad: '✖' }

export default function Profiler({ detail, info }: { detail: TableDetail; info?: Info }) {
  const { owner, name } = detail
  const meta = useQuery({ queryKey: ['profile-meta', owner, name], queryFn: () => api.profileMetadata(owner, name) })
  const scan = useMutation({ mutationFn: (mode: 'sample' | 'exact') => api.profileScan(owner, name, mode) })
  const [column, setColumn] = useState<string | null>(null)

  const m = meta.data
  const t = m?.table
  const scanData = scan.data
  const scanMode = scanData?.source.mode

  const runExact = () => {
    const rows = t?.num_rows
    const msg =
      `전체 행을 읽어 정확한 NULL·고유값·최소/최대를 계산합니다.\n` +
      (rows ? `통계상 약 ${fmtInt(rows)}행입니다. ` : '행 수 통계가 없습니다. ') +
      `DB 에 부하를 줄 수 있고 최대 ${info?.limits.exact_profile_timeout_sec ?? 120}초 후 중단됩니다.\n계속할까요?`
    if (window.confirm(msg)) scan.mutate('exact')
  }

  return (
    <div className="profile scroll">
      <div className="legend">
        {(Object.keys(SOURCE_INFO) as ProfileSourceKind[]).map((s) => (
          <div key={s} className="legend-item">
            <SourceBadge source={s} />
            <span className="muted small">{SOURCE_INFO[s].desc}</span>
          </div>
        ))}
      </div>

      {meta.error && <div className="notice err">{errorText(meta.error)}</div>}
      {meta.isLoading && <div className="muted">메타데이터와 통계를 읽는 중…</div>}

      {t && (
        <div className="cards">
          <div className="card">
            <div className="card-head">행 수 <SourceBadge source="stats" /></div>
            <strong>{t.type === 'VIEW' ? '-' : fmtInt(t.num_rows)}</strong>
            <small>
              {t.type === 'VIEW'
                ? '뷰는 통계가 없습니다'
                : t.num_rows === null
                  ? '통계 없음 — 샘플/정확 프로파일로 확인'
                  : `통계 샘플 ${fmtInt(t.sample_size)}행 기준`}
            </small>
            {scanData && (
              <small className="scan-note">
                <SourceBadge source={scanMode} /> {scanMode === 'exact' ? `실제 ${fmtInt(scanData.rows_scanned)}행` : `샘플 ${fmtInt(scanData.rows_scanned)}행 읽음`}
              </small>
            )}
          </div>
          <div className="card">
            <div className="card-head">용량 <SourceBadge source={t.size?.source} /></div>
            <strong>{fmtBytes(t.size?.bytes)}</strong>
            <small>{t.size?.note ?? '뷰는 저장 공간이 없습니다'}</small>
            {t.avg_row_len !== null && <small>평균 행 길이 {t.avg_row_len} B · 블록 {fmtInt(t.blocks)}</small>}
          </div>
          <div className={`card ${t.last_analyzed === null || t.stale_stats === 'YES' || (t.stats_age_days ?? 0) > 30 ? 'warn' : 'ok'}`}>
            <div className="card-head">통계 수집 시점 <SourceBadge source="stats" /></div>
            <strong>{t.last_analyzed ? daysAgo(t.last_analyzed) : '없음'}</strong>
            <small>
              {t.last_analyzed ? fmtDate(t.last_analyzed) : t.type === 'VIEW' ? '뷰' : '한 번도 수집되지 않음'}
              {t.stale_stats === 'YES' && ' · STALE'}
              {t.stats_locked && ' · 잠김'}
            </small>
          </div>
          <div className="card">
            <div className="card-head">데이터 변경 <SourceBadge source="metadata" /></div>
            <strong>
              {t.modifications
                ? fmtInt((t.modifications.inserts ?? 0) + (t.modifications.updates ?? 0) + (t.modifications.deletes ?? 0))
                : '-'}
            </strong>
            <small>
              {t.modifications
                ? `통계 이후 +${fmtInt(t.modifications.inserts)} / ~${fmtInt(t.modifications.updates)} / -${fmtInt(t.modifications.deletes)} · 마지막 ${fmtDate(t.modifications.timestamp)}`
                : '통계 이후 기록된 변경 없음 (ALL_TAB_MODIFICATIONS)'}
            </small>
          </div>
          <div className="card">
            <div className="card-head">구조 변경 <SourceBadge source="metadata" /></div>
            <strong>{daysAgo(t.last_ddl_time) || '-'}</strong>
            <small>최근 DDL {fmtDate(t.last_ddl_time)} · 생성 {fmtDate(t.created)}</small>
          </div>
        </div>
      )}

      {m && (
        <div className="quality">
          <h3 className="section-title">품질 지표</h3>
          <div className="quality-list">
            {m.quality.map((q, i) => (
              <div key={i} className={`q-item q-${q.level}`}>
                <span className="q-icon">{LEVEL_ICON[q.level]}</span>
                <div>
                  <div className="row gap-sm">
                    <strong>{q.title}</strong>
                    <SourceBadge source={q.source} />
                  </div>
                  <div className="muted small">{q.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {m && (
        <>
          <div className="row gap-sm section-title">
            <h3>컬럼 프로파일</h3>
            <span className="spacer" />
            {scan.isPending && <span className="muted">계산 중… <span className="spinner" /></span>}
            {scanData && !scan.isPending && (
              <span className="muted small">
                <SourceBadge source={scanMode} /> {scanData.source.label} · {fmtInt(scanData.rows_scanned)}행 · {fmtMs(scanData.elapsed_ms)}
              </span>
            )}
            <button className="btn sm" disabled={scan.isPending} onClick={() => scan.mutate('sample')}>
              샘플 프로파일
            </button>
            <button className="btn sm" disabled={scan.isPending} onClick={runExact}>
              정확한 프로파일 (전체 스캔)
            </button>
          </div>
          {scan.error && <div className="notice err">{errorText(scan.error)}</div>}

          <div className="profile-body">
            <div className="grid-wrap">
              <ColumnTable cols={m.columns} scan={scanData} selected={column} onSelect={setColumn} numRows={t?.num_rows ?? null} />
            </div>
            {column ? (
              <DistributionPanel key={column} owner={owner} table={name} column={m.columns.find((c) => c.name === column)!} />
            ) : (
              <div className="dist-card empty-dist muted">컬럼을 선택하면 값 분포를 보여 줍니다.</div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function ColumnTable({
  cols, scan, selected, onSelect, numRows,
}: {
  cols: MetaColumn[]
  scan?: ScanProfile
  selected: string | null
  onSelect: (c: string) => void
  numRows: number | null
}) {
  const mode = scan?.source.mode
  return (
    <table className="grid profile-grid">
      <thead>
        <tr className="group-row">
          <th colSpan={2}></th>
          <th colSpan={4} className="grp grp-stats">기존 통계{numRows === null ? ' (없음)' : ''}</th>
          <th colSpan={4} className={`grp grp-${mode ?? 'none'}`}>
            {mode === 'exact' ? '정확(전체 스캔)' : mode === 'sample' ? '샘플링' : '샘플/정확 — 아직 실행 안 함'}
          </th>
        </tr>
        <tr>
          <th>컬럼</th>
          <th>타입</th>
          <th className="num">NULL 비율</th>
          <th className="num">고유값</th>
          <th>최소 / 최대</th>
          <th>히스토그램</th>
          <th className="num">NULL 비율</th>
          <th className="num">고유값</th>
          <th>최소</th>
          <th>최대</th>
        </tr>
      </thead>
      <tbody>
        {cols.map((c) => {
          const s: ScanColumn | undefined = scan?.columns[c.name]
          return (
            <tr key={c.name} className={`clickable ${selected === c.name ? 'selected' : ''}`} onClick={() => onSelect(c.name)}>
              <td><strong>{c.name}</strong>{c.comment && <div className="muted small truncate">{c.comment}</div>}</td>
              <td className="mono small">{c.type}</td>
              <td className="num"><RateBar ratio={c.null_ratio} /></td>
              <td className="num">{fmtInt(c.num_distinct)}</td>
              <td className="small mono minmax">
                {c.low !== undefined && c.low !== null ? `${fmtCell(c.low)} ~ ${fmtCell(c.high ?? null)}` : <span className="muted">-</span>}
              </td>
              <td className="small">{c.histogram && c.histogram !== 'NONE' ? `${c.histogram} (${c.num_buckets})` : <span className="muted">-</span>}</td>
              <td className="num">{s ? <RateBar ratio={s.null_ratio} /> : ''}</td>
              <td className="num" title={s?.distinct_ratio != null ? `고유 비율 ${fmtPct(s.distinct_ratio)}` : undefined}>
                {s ? fmtInt(s.distinct) : ''}
                {s && mode === 'sample' && s.distinct != null && <span className="muted small"> ≈</span>}
              </td>
              <td className="small mono minmax">{s ? fmtCell(s.min ?? null) : ''}</td>
              <td className="small mono minmax">{s ? fmtCell(s.max ?? null) : ''}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function RateBar({ ratio }: { ratio: number | null | undefined }) {
  if (ratio === null || ratio === undefined) return <span className="muted">-</span>
  return (
    <div className="ratebar">
      <div className="ratebar-track">
        <div className={`ratebar-fill ${ratio >= 0.5 ? 'danger' : ''}`} style={{ width: `${Math.min(100, ratio * 100)}%` }} />
      </div>
      <span>{fmtPct(ratio)}</span>
    </div>
  )
}

function DistributionPanel({ owner, table, column }: { owner: string; table: string; column: MetaColumn }) {
  const hasHistogram = !!column.histogram && column.histogram !== 'NONE'
  const [source, setSource] = useState<'stats' | 'sample'>(hasHistogram ? 'stats' : 'sample')
  const dist = useQuery({
    queryKey: ['dist', owner, table, column.name, source],
    queryFn: () => api.distribution(owner, table, column.name, source),
  })
  const d = dist.data
  const bars = d?.values ?? d?.bins ?? []

  return (
    <div className="dist-card">
      <div className="dist-head">
        <div className="row gap-sm">
          <h3>{column.name}</h3>
          <span className="muted small">{column.type}</span>
        </div>
        <div className="seg">
          <button className={source === 'stats' ? 'active' : ''} onClick={() => setSource('stats')}>
            기존 통계 히스토그램
          </button>
          <button className={source === 'sample' ? 'active' : ''} onClick={() => setSource('sample')}>
            샘플 분포
          </button>
        </div>
        {d && (
          <div className="muted small">
            <SourceBadge source={d.source} />{' '}
            {d.source === 'stats'
              ? d.kind === 'none'
                ? ''
                : `${d.histogram} · ${d.note ?? ''} · 수집 ${fmtDate(d.last_analyzed)}`
              : `${d.sample?.label ?? ''} · ${fmtInt(d.rows)}행 중 NULL ${fmtInt(d.nulls)}`}
          </div>
        )}
      </div>
      {dist.isFetching && <div className="chart-placeholder">계산 중… <span className="spinner" /></div>}
      {dist.error && <div className="notice err">{errorText(dist.error)}</div>}
      {d && !dist.isFetching && d.kind === 'none' && <div className="chart-placeholder">{d.reason}</div>}
      {d && !dist.isFetching && d.kind !== 'none' && bars.length === 0 && <div className="chart-placeholder">값이 없습니다.</div>}
      {d && !dist.isFetching && bars.length > 0 && (
        <>
          <ResponsiveContainer width="100%" height={d.kind === 'categorical' ? Math.max(220, bars.length * 26) : 300}>
            {d.kind === 'categorical' ? (
              <BarChart data={bars} layout="vertical" margin={{ left: 8, right: 24 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tickFormatter={(v) => fmtInt(v)} fontSize={11} />
                <YAxis type="category" dataKey="label" width={120} fontSize={11} interval={0} />
                <Tooltip formatter={(v) => fmtInt(Number(v))} />
                <Bar dataKey="count" name="행 수" fill="#4f5dff" radius={[0, 4, 4, 0]} />
              </BarChart>
            ) : (
              <BarChart data={bars} margin={{ left: 8, right: 8, bottom: 40 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" angle={-40} textAnchor="end" fontSize={10} interval={0} height={60} />
                <YAxis tickFormatter={(v) => fmtInt(v)} fontSize={11} />
                <Tooltip formatter={(v) => fmtInt(Number(v))} />
                <Bar dataKey="count" name="행 수" fill="#4f5dff" radius={[4, 4, 0, 0]} />
              </BarChart>
            )}
          </ResponsiveContainer>
          {d.others !== undefined && d.others > 0 && (
            <div className="muted small">상위 {bars.length}개 외 기타 {fmtInt(d.others)}행</div>
          )}
          {d.min !== undefined && (
            <div className="muted small">최소 {fmtCell(d.min ?? null)} · 최대 {fmtCell(d.max ?? null)}</div>
          )}
        </>
      )}
    </div>
  )
}
