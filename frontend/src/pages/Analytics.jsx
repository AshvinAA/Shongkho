import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import { getDashboard, getRunStatus, startRun } from '../api/analytics.js'
import { SegmentedControl, Button } from '../components/ui/index.jsx'
import { fmtMoney } from '../utils/format.js'
import { chartColor } from '../components/analytics/chartPalette.js'
import SalesTrend from '../components/analytics/SalesTrend.jsx'
import EmployeeRace from '../components/analytics/EmployeeRace.jsx'
import TopProducts from '../components/analytics/TopProducts.jsx'
import { Skeleton } from '../components/ui/index.jsx'

const PERIOD_OPTIONS = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
]

const POLL_MS = 1500

/**
 * Owner-only Analytics page.
 *
 * BI layout: header with run lifecycle + last-analyzed stamp, a four-card
 * KPI strip (revenue / profit / orders / avg basket, each with delta and
 * sparkline), then the three snapshot sections. "Run analysis" is the ONE
 * run trigger (409 = a run is already live — resume polling it).
 *
 * Protik's AI commentary and chat live on their own /protik page.
 * A floating Day/Week/Month bubble follows scroll, so the period stays
 * switchable without scrolling back up to the header.
 */
export default function Analytics() {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'

  const [period, setPeriod] = useState('week')
  const [metric, setMetric] = useState('revenue')
  const [sections, setSections] = useState({})
  const [generatedAt, setGeneratedAt] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Run lifecycle state: null = idle, else { id, status, reason }
  const [run, setRun] = useState(null)
  const pollRef = useRef(null)

  const loadDashboard = useCallback(async (p = period, quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const data = await getDashboard(p)
      setSections(data.sections || {})
      setGeneratedAt(data.generated_at)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [period])

  useEffect(() => {
    if (isOwner) loadDashboard(period)
  }, [isOwner, period, loadDashboard])

  // Cleanup the poller on unmount.
  useEffect(() => () => clearInterval(pollRef.current), [])

  // Floating period bubble: watch the header controls with an
  // IntersectionObserver; once they scroll out of view (behind the sticky
  // topbar), surface a Day/Week/Month bubble in the corner so switching
  // periods never requires scrolling back to the top.
  const [controlsOffscreen, setControlsOffscreen] = useState(false)
  const controlsSentinelRef = useRef(null)

  useEffect(() => {
    const el = controlsSentinelRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(
      ([entry]) => setControlsOffscreen(!entry.isIntersecting),
      // Discount the sticky topbar (60px) so the bubble appears only when
      // the header controls are actually hidden behind it.
      { rootMargin: '-60px 0px 0px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  function pollRun(runId) {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const status = await getRunStatus(runId)
        setRun({ id: runId, status: status.status, reason: status.failure_reason })
        if (status.status === 'COMPLETED' || status.status === 'FAILED') {
          clearInterval(pollRef.current)
          if (status.status === 'COMPLETED') loadDashboard(period, true)
        }
      } catch (e) {
        if (e.status === 404) {
          clearInterval(pollRef.current)
          setRun({ id: runId, status: 'FAILED', reason: 'Run not found' })
        }
        // Transient network errors: keep polling.
      }
    }, POLL_MS)
  }

  async function handleRun() {
    setError(null)
    try {
      const res = await startRun(period)
      setRun({ id: res.run_id, status: res.status || 'QUEUED' })
      if (res.status === 'COMPLETED') {
        // Sync executor: the pipeline already finished — refresh now.
        await loadDashboard(period, true)
      } else {
        // Celery executor: poll until the chord completes.
        pollRun(res.run_id)
      }
    } catch (e) {
      if (e.status === 409 && run?.id) {
        // A run is already in flight — resume polling it.
        pollRun(run.id)
      } else if (e.status === 409) {
        setError('An analysis is already running. Give it a moment…')
      } else {
        setError(e.message)
      }
    }
  }

  if (!isOwner) {
    return <p className="muted">Analytics are available to store owners only.</p>
  }

  const running = run && (run.status === 'QUEUED' || run.status === 'RUNNING')
  const runLabel = !run
    ? 'Run analysis'
    : running
      ? run.status === 'QUEUED' ? 'Queued…' : 'Running…'
      : 'Run analysis'
  const empty = !loading && !sections.sales && !sections.employees && !sections.products

  return (
    <div className="page analytics-page">
      <div className="page-header analytics-header">
        <div>
          <h1>Analytics</h1>
          <p className="muted analytics-stamp">
            {generatedAt ? (
              <>
                Last analyzed <strong>{new Date(generatedAt).toLocaleString()}</strong>
              </>
            ) : (
              'No analysis yet — snapshots appear after your first run'
            )}
            {' · '}frozen per run
          </p>
        </div>
        <div className="analytics-actions" ref={controlsSentinelRef}>
          <SegmentedControl options={PERIOD_OPTIONS} value={period} onChange={setPeriod} ariaLabel="Analysis period" />
          <Button onClick={handleRun} loading={!!running}>
            {runLabel}
          </Button>
        </div>
        {run?.status === 'FAILED' && (
          <button type="button" className="link-btn" onClick={() => setRun(null)}>
            Dismiss error
          </button>
        )}
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {run?.status === 'FAILED' && (
        <div className="alert alert-error">
          Last run failed{run.reason ? `: ${run.reason}` : ''}. You can retry.
        </div>
      )}

      {loading && !sections.sales ? (
        <div className="bi-skeletons" aria-label="Loading analytics">
          <Skeleton height="96px" />
          <Skeleton height="320px" />
          <Skeleton height="320px" />
          <Skeleton height="320px" />
        </div>
      ) : (
        <>
          {sections.sales && <KpiStrip sales={sections.sales} />}

          {empty && (
            <div className="alert alert-info analytics-first-run">
              No analysis for this period yet — hit <strong>Run analysis</strong> (top right) to generate your first snapshot.
            </div>
          )}

          <section className="analytics-section">
            {sections.sales ? (
              <SalesTrend data={sections.sales} metric={metric} onMetricChange={setMetric} />
            ) : (
              <EmptySection
                title="Sales trend"
                body="Revenue and profit per hour/day, with comparisons to the previous period, appear after your first run."
              />
            )}
          </section>

          <section className="analytics-section">
            {sections.employees ? (
              <EmployeeRace data={sections.employees} metric={metric} onMetricChange={setMetric} />
            ) : (
              <EmptySection title="Employee race" body="How your staff compare on revenue and profit appears after your first run." />
            )}
          </section>

          <section className="analytics-section">
            {sections.products ? (
              <TopProducts data={sections.products} />
            ) : (
              <EmptySection title="Top products" body="Products ranked by revenue and profit appear after your first run." />
            )}
          </section>
        </>
      )}

      {/* Floating Day/Week/Month bubble — its control only mounts while the
          header controls are scrolled away, so there is never a duplicate
          tablist on screen (or in the accessibility tree). */}
      <div className={`analytics-period-bubble${controlsOffscreen ? ' analytics-period-bubble-on' : ''}`}>
        {controlsOffscreen && (
          <SegmentedControl
            options={PERIOD_OPTIONS}
            value={period}
            onChange={setPeriod}
            ariaLabel="Analysis period"
            size="sm"
          />
        )}
      </div>
    </div>
  )
}

/**
 * Four KPI cards derived from the sales snapshot: revenue, profit, orders,
 * and average basket (revenue ÷ orders, vs the previous period).
 */
function KpiStrip({ sales }) {
  const p = sales.period
  const cur = sales.current || {}
  const prev = sales.previous || {}
  const basketNow = cur.orders ? cur.revenue / cur.orders : 0
  const basketPrev = prev.orders ? prev.revenue / prev.orders : 0
  const basketDelta = basketPrev ? (basketNow / basketPrev - 1) * 100 : null

  const cards = [
    { label: `Revenue this ${p}`, value: fmtMoney(cur.revenue), delta: sales.change_pct?.revenue, tone: 'revenue', detail: `prev ${fmtMoney(prev.revenue)}`, series: sales.series?.map((b) => b.revenue) },
    { label: `Profit this ${p}`, value: fmtMoney(cur.profit), delta: sales.change_pct?.profit, tone: 'profit', detail: `prev ${fmtMoney(prev.profit)}`, series: sales.series?.map((b) => b.profit) },
    { label: `Orders this ${p}`, value: String(cur.orders ?? 0), delta: sales.change_pct?.orders, tone: 'orders', detail: `prev ${prev.orders ?? 0}`, series: sales.series?.map((b) => b.orders) },
    { label: 'Avg basket', value: fmtMoney(basketNow), delta: basketDelta === null ? null : Math.round(basketDelta * 10) / 10, detail: `prev ${fmtMoney(basketPrev)}`, series: null },
  ]

  return (
    <div className="bi-kpi-strip">
      {cards.map((c) => (
        <div key={c.label} className={`ui-stat ui-stat-${c.tone}`}>
          <span className="ui-stat-label">{c.label}</span>
          <span className="ui-stat-value">{c.value}</span>
          {c.delta !== undefined && c.delta !== null ? (
            <span className={`ui-delta ${c.delta > 0 ? 'ui-delta-up' : c.delta < 0 ? 'ui-delta-down' : 'ui-delta-neutral'}`}>
              {c.delta > 0 ? '▲' : c.delta < 0 ? '▼' : '▬'} {Math.abs(c.delta)}%
            </span>
          ) : null}
          {c.series?.length > 1 && <Spark points={c.series} stroke={chartColor(c.tone)} />}
          {c.detail ? <span className="ui-stat-detail">{c.detail}</span> : null}
        </div>
      ))}
    </div>
  )
}

/** Tiny inline sparkline (pure SVG — no Recharts overhead at KPI size). */
function Spark({ points, stroke }) {
  const w = 120
  const h = 28
  const max = Math.max(...points, 1)
  const min = Math.min(...points, 0)
  const span = max - min || 1
  const step = w / (points.length - 1)
  const d = points
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(h - 3 - ((v - min) / span) * (h - 6)).toFixed(1)}`)
    .join(' ')
  return (
    <svg className="bi-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={d} fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

/**
 * Static placeholder for a section with no snapshot yet.
 * The ONE run button lives in the page header — never per-section.
 */
function EmptySection({ title, body }) {
  return (
    <div className="card empty-section">
      <h3 className="card-title">{title}</h3>
      <p className="muted">{body}</p>
    </div>
  )
}
