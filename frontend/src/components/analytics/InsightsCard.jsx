/**
 * Business insights — Track A "insights" snapshot (Part A, LLM engine).
 *
 * `data` is the frozen insights payload written per run:
 *   success:  { summary, observations: [{ text, basis }], areas_to_watch: [] }
 *   degraded: { summary: null, degraded: true, degraded_reason }
 *   legacy:   { summary: null, pending: "..." }          (stage-1 placeholder)
 *
 * The card is honest about degraded runs: the prose is unavailable, the
 * reason is shown small, and the charts above remain the source of truth.
 */
export default function InsightsCard({ data }) {
  if (!data) return null

  // Stage-1 placeholder row (should no longer be written, but old
  // snapshots may still exist).
  if (data.pending) {
    return (
      <div className="analytics-panel">
        <h3 className="card-title">Business insights</h3>
        <p className="muted">{data.pending}</p>
      </div>
    )
  }

  // Degraded run: the LLM step could not produce validated prose.
  // Not an error state — the three data sections are still valid.
  if (data.degraded) {
    return (
      <div className="analytics-panel">
        <h3 className="card-title">Business insights</h3>
        <p className="muted">
          Automated commentary is unavailable for this run — your charts
          below are still up to date.
        </p>
        {data.degraded_reason && (
          <p className="card-sub" title={data.degraded_reason}>
            Reason: {data.degraded_reason}
          </p>
        )}
      </div>
    )
  }

  const observations = Array.isArray(data.observations) ? data.observations : []
  const watch = Array.isArray(data.areas_to_watch) ? data.areas_to_watch : []

  return (
    <div className="analytics-panel">
      <h3 className="card-title">Business insights</h3>

      {data.summary && <p className="insights-summary">{data.summary}</p>}

      {observations.length > 0 && (
        <ul className="insights-list">
          {observations.map((obs, i) => (
            <li key={i}>{obs.text}</li>
          ))}
        </ul>
      )}

      {watch.length > 0 && (
        <>
          <h4 className="insights-watch-title">Areas to watch</h4>
          <ul className="insights-list insights-watch">
            {watch.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
