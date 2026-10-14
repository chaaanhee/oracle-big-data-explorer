import { useMemo, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { PLSQL, sql as sqlLang } from '@codemirror/lang-sql'
import { keymap } from '@codemirror/view'
import { Prec } from '@codemirror/state'
import { api, download } from '../api'
import { newId, useStored, type HistoryItem, type SavedQuery } from '../storage'
import { errorText, fmtInt, fmtMs } from '../format'
import type { Info } from '../types'
import ResultGrid from './ResultGrid'

const DEFAULT_SQL = `-- 읽기 전용: SELECT / WITH 문만 실행됩니다.
SELECT owner, table_name, num_rows, last_analyzed
FROM all_tables
WHERE owner NOT IN ('SYS', 'SYSTEM')
ORDER BY num_rows DESC NULLS LAST`

export default function SqlWorkbench({ info }: { info?: Info }) {
  const [draft, setDraft] = useStored<string>('sql-draft', '')
  const [history, setHistory] = useStored<HistoryItem[]>('sql-history', [])
  const [saved, setSaved] = useStored<SavedQuery[]>('sql-saved', [])
  const [panel, setPanel] = useState<'history' | 'saved'>('history')
  const [maxRows, setMaxRows] = useState(1000)
  const [lastSql, setLastSql] = useState('')
  const editor = useRef<ReactCodeMirrorRef>(null)
  const text = draft || DEFAULT_SQL
  const limits = info?.limits

  const run = useMutation({
    mutationFn: (sql: string) => api.sql(sql, maxRows),
    onMutate: (sql) => setLastSql(sql),
    onSuccess: (r, sql) =>
      setHistory((h) => [
        { id: newId(), sql, at: Date.now(), ok: true, rows: r.row_count, elapsed_ms: r.elapsed_ms },
        ...h.filter((x) => x.sql !== sql),
      ].slice(0, 100)),
    onError: (e, sql) =>
      setHistory((h) => [
        { id: newId(), sql, at: Date.now(), ok: false, error: errorText(e) },
        ...h.filter((x) => x.sql !== sql),
      ].slice(0, 100)),
  })

  const runRef = useRef<() => void>(() => {})
  runRef.current = () => {
    const view = editor.current?.view
    const sel = view?.state.selection.main
    const selected = view && sel && !sel.empty ? view.state.sliceDoc(sel.from, sel.to) : ''
    const sql = (selected || view?.state.doc.toString() || text).trim()
    if (sql && !run.isPending) run.mutate(sql)
  }

  const extensions = useMemo(
    () => [
      sqlLang({ dialect: PLSQL, upperCaseKeywords: true }),
      Prec.highest(
        keymap.of([
          { key: 'Mod-Enter', run: () => { runRef.current(); return true } },
        ]),
      ),
    ],
    [],
  )

  const saveCurrent = () => {
    const name = window.prompt('즐겨찾기 쿼리 이름', text.split('\n').find((l) => l.trim() && !l.startsWith('--'))?.slice(0, 40))
    if (!name) return
    setSaved((s) => [{ id: newId(), name, sql: text, at: Date.now() }, ...s])
    setPanel('saved')
  }

  const r = run.data

  return (
    <div className="sql-view-wrap">
      <header className="topbar">
        <div className="topbar-title">
          <h1>SQL 워크벤치</h1>
        </div>
        {limits && (
          <div className="limits">
            <span className="badge badge-ok">읽기 전용 트랜잭션</span>
            <span className="badge">SELECT·WITH 만 허용</span>
            <span className="badge">시간 제한 {limits.query_timeout_sec}초</span>
            <span className="badge">최대 {fmtInt(limits.sql_max_rows)}행 표시</span>
            <span className="badge">동시 실행 {limits.sql_concurrency}개</span>
          </div>
        )}
      </header>

      <div className="content sql-content">
        <div className="sql-top">
          <div className="editor">
            <CodeMirror
              ref={editor}
              value={text}
              height="240px"
              extensions={extensions}
              onChange={(v) => setDraft(() => v)}
              basicSetup={{ foldGutter: false }}
            />
            <div className="editor-bar">
              <button className="btn primary" disabled={run.isPending} onClick={() => runRef.current()}>
                {run.isPending ? '실행 중…' : '▶ 실행'}
              </button>
              <span className="muted small">Ctrl+Enter · 일부를 선택하면 선택한 부분만 실행</span>
              <span className="spacer" />
              <span className="muted small">최대 행</span>
              <select value={maxRows} onChange={(e) => setMaxRows(Number(e.target.value))}>
                {[100, 1000, 5000, 10000, 50000].filter((n) => !limits || n <= limits.sql_max_rows).map((n) => (
                  <option key={n} value={n}>{fmtInt(n)}</option>
                ))}
              </select>
              <button className="btn sm" onClick={saveCurrent}>☆ 즐겨찾기 저장</button>
              <button className="btn sm ghost" onClick={() => setDraft(() => '')}>초기화</button>
            </div>
          </div>

          <div className="sql-side">
            <div className="seg full">
              <button className={panel === 'history' ? 'active' : ''} onClick={() => setPanel('history')}>
                실행 이력 {history.length || ''}
              </button>
              <button className={panel === 'saved' ? 'active' : ''} onClick={() => setPanel('saved')}>
                즐겨찾기 {saved.length || ''}
              </button>
            </div>
            <div className="sql-list">
              {panel === 'history' && (
                <>
                  {history.length === 0 && <div className="hint">실행한 쿼리가 여기에 기록됩니다.</div>}
                  {history.length > 0 && (
                    <button className="icon-btn" onClick={() => setHistory(() => [])}>이력 비우기</button>
                  )}
                  {history.map((h) => (
                    <div key={h.id} className="sql-item" onClick={() => setDraft(() => h.sql)} title={h.error ?? h.sql}>
                      <pre>{h.sql}</pre>
                      <div className="sql-meta">
                        <span className={h.ok ? 'ok-text' : 'bad-text'}>{h.ok ? `${fmtInt(h.rows)}행 · ${fmtMs(h.elapsed_ms)}` : '실패'}</span>
                        <span className="muted">{new Date(h.at).toLocaleString()}</span>
                      </div>
                    </div>
                  ))}
                </>
              )}
              {panel === 'saved' && (
                <>
                  {saved.length === 0 && <div className="hint">자주 쓰는 쿼리를 "☆ 즐겨찾기 저장" 으로 보관하세요.</div>}
                  {saved.map((s) => (
                    <div key={s.id} className="sql-item" onClick={() => setDraft(() => s.sql)}>
                      <div className="row">
                        <strong>★ {s.name}</strong>
                        <span className="spacer" />
                        <button
                          className="icon-btn"
                          title="삭제"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (window.confirm(`'${s.name}' 을(를) 삭제할까요?`)) setSaved((x) => x.filter((y) => y.id !== s.id))
                          }}
                        >
                          ✕
                        </button>
                      </div>
                      <pre>{s.sql}</pre>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        </div>

        <div className="statusbar">
          <div className="row gap-sm">
            {run.isPending && <span className="muted">실행 중… <span className="spinner" /></span>}
            {r && !run.isPending && !run.error && (
              <>
                <strong>{fmtInt(r.row_count)}행</strong>
                <span className="muted">· {fmtMs(r.elapsed_ms)}</span>
                {r.truncated && (
                  <span className="warn-text">
                    · 결과가 더 있지만 {fmtInt(r.row_count)}행까지만 가져왔습니다 (전체는 CSV 로 받기)
                  </span>
                )}
              </>
            )}
          </div>
          {r && !run.error && (
            <button
              className="btn sm"
              title={`최대 ${fmtInt(limits?.export_max_rows)}행까지 서버에서 스트리밍합니다`}
              onClick={() => download(api.sqlExportUrl(lastSql))}
            >
              CSV 다운로드 (전체 결과)
            </button>
          )}
        </div>
        {run.error && <div className="notice err pre">{errorText(run.error)}</div>}

        {r && !run.error ? (
          <ResultGrid columns={r.columns.map((c) => ({ name: c.name, type: c.type }))} rows={r.rows} loading={run.isPending} />
        ) : (
          !run.error && <div className="empty small muted">쿼리를 실행하면 결과가 여기에 표시됩니다.</div>
        )}
      </div>
    </div>
  )
}
