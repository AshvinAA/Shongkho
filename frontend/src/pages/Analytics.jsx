import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import { getDashboard, getRunStatus, startRun } from '../api/analytics.js'
import { SegmentedControl } from '../components/analytics/common.jsx'
import SalesTrend from '../components/analytics/SalesTrend.jsx'
import EmployeeRace from '../components/analytics/EmployeeRace.jsx'
import TopProducts from '../components/analytics/TopProducts.jsx'

const PERIOD_OPTIONS = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
]
const METRIC_OPTIONS = [
  { value: 'revenue', label: 'Revenue' },
  { value: 'profit', label: 'Profit' },
]

const POLL_MS = 1500

/**
 * Owner-only Analytics page (Track A, stage 1).
 *
 * Loads the latest completed snapshots for the selected period, shows
 * the three graph sections, and offers a "Run analysis" button that
 * starts a run and polls its status (409 = one is already running —
 * just keep polling it). No LLM yet: the insights card shows the
 * stage-2 placeholder written by the pipeline.
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
  const empty = !loading && !sections.sales && !sections.employees && !sections.products

  return (
    <div className="page analytics-page">
      <div className="page-header">
        <div>
          <h1>Analytics</h1>
          <p className="muted">
            Frozen snapshots per run ·{' '}
            {generatedAt ? `last updated ${new Date(generatedAt).toLocaleString()}` : 'no analysis yet'}
          </p>
        </div>
        <div className="analytics-actions">
          <SegmentedControl options={PERIOD_OPTIONS} value={period} onChange={setPeriod} />
          <button
            type="button"
            className="btn"
            onClick={handleRun}
            disabled={running}
          >
            {running ? `⏳ ${run.status.toLowerCase()}…` : '▶ Run analysis'}
          </button>
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

      {loading ? (
        <p className="muted">Loading analytics…</p>
      ) : (
        <>
          {empty && (
            <div className="alert alert-info analytics-first-run">
              No analysis for this period yet — hit <strong>▶ Run analysis</strong> (top right) to generate your first snapshot.
            </div>
          )}

          <section className="analytics-section">
            {sections.sales ? (
              <SalesTrend data={sections.sales} metric={metric} />
            ) : (
              <EmptySection
                title="Sales trend"
                body="Revenue and profit per hour/day, with comparisons to the previous period, appear after your first run."
              />
            )}
          </section>

          <section className="analytics-section">
            {sections.employees ? (
              <EmployeeRace data={sections.employees} metric={metric} />
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

          <section className="analytics-section">
            {sections.insights && !sections.insights.pending ? (
              <p className="card">{sections.insights.summary}</p>
            ) : (
              <p className="muted">
                {sections.insights?.pending || 'Business insights arrive with stage 2 (LLM).'}
              </p>
            )}
          </section>
        </>
      )}
    </div>
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
