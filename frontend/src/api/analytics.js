import { get, post, qs } from './client.js'

/**
 * Trigger a full analytics run for the owner's store.
 * Returns 202 { run_id, status, period }. Throws with .status === 409
 * while another run is already queued/running.
 */
export function startRun(period = 'week') {
  return post('/analytics/run', { period })
}

/** Poll one run's lifecycle: { run_id, status, failure_reason, ... } */
export function getRunStatus(runId) {
  return get(`/analytics/run/${encodeURIComponent(runId)}/status`)
}

/**
 * Latest completed snapshot per section for one period.
 * period: 'day' | 'week' | 'month'
 * Returns { period, generated_at, sections: { sales?, employees?, products?, insights? } }
 */
export function getDashboard(period = 'week') {
  return get(`/analytics/dashboard${qs({ period })}`)
}
