import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ReferenceDot,
} from 'recharts'
import { fmtMoney } from '../../utils/format.js'
import { DeltaChip, SegmentedControl } from './common.jsx'
import { chartColor, chartSeries } from './chartPalette.js'
import Avatar from '../Avatar.jsx'

const AXIS_TICK = { fontSize: 11, fill: 'var(--chart-axis, #5c6f68)' }

const METRIC_OPTIONS = [
  { value: 'revenue', label: 'Revenue' },
  { value: 'profit', label: 'Profit' },
]

/**
 * Employee race — Track A "employees" snapshot.
 *
 * Two views from one frozen snapshot:
 *   1. Race over time (line chart): cumulative revenue/profit per
 *      employee across the period's buckets, avatar headmarkers at each
 *      line's end. Driven by `race_series` (employee ids -> cumulative
 *      arrays aligned with `labels`).
 *   2. Final standings: ranked rows — rank number, avatar, name,
 *      metric-colored bar, value, delta chip — plus both money figures
 *      and the per-person delta, always visible.
 *
 * The metric toggle is lifted to the page; both views follow it with no
 * refetch (both series ship inside the snapshot).
 */
export default function EmployeeRace({ data, metric = 'revenue', onMetricChange }) {
  if (!data?.employees) return null

  const lanes = data.employees
    .map((e) => ({ ...e, value: e[metric] ?? 0 }))
    .sort((a, b) => b.value - a.value)
  const leader = lanes[0]
  const rs = data.race_series
  const maxVal = Math.max(...lanes.map((l) => l.value), 1)

  // ---- race-over-time chart data ----
  let raceRows = []
  let racers = []
  if (rs?.labels?.length && rs[metric]) {
    racers = Object.keys(rs[metric])
      .map((id) => ({
        id,
        lane: lanes.find((l) => String(l.employee_id) === id)
          || { name: `User #${id}`, photo: null },
      }))
      .sort((a, b) => {
        const av = rs[metric][a.id]?.at(-1) ?? 0
        const bv = rs[metric][b.id]?.at(-1) ?? 0
        return bv - av
      })
    // Wide buckets (month = ~30) get thinned for readable x axes.
    const step = Math.max(1, Math.ceil(rs.labels.length / 31))
    raceRows = rs.labels.map((label, i) => {
      const row = { label }
      for (const r of racers) {
        row[r.id] = rs[metric][r.id]?.[i] ?? 0
      }
      return row
    }).filter((_, i) => i % step === 0)
  }

  return (
    <div className="analytics-panel">
      <div className="analytics-panel-head">
        <h3 className="card-title">Employee race — {metric}</h3>
        <div className="analytics-panel-controls">
          <span className="race-leader-chip">
            🏁 Leader: <strong>{leader?.name ?? '—'}</strong>
          </span>
          <SegmentedControl
            options={METRIC_OPTIONS}
            value={metric}
            onChange={onMetricChange}
            ariaLabel="Race metric"
            size="sm"
          />
        </div>
      </div>

      {lanes.length === 0 ? (
        <p className="muted">No employee sales recorded this {data.period} yet.</p>
      ) : (
        <>
          {raceRows.length > 0 && (
            <div className="chart-wrap race-time-wrap">
              <h4 className="race-subtitle">
                {metric === 'revenue' ? 'Revenue' : 'Profit'} race over the {data.period} (cumulative)
              </h4>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={raceRows} margin={{ top: 18, right: 24, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={chartColor('grid')} />
                  <XAxis dataKey="label" tick={AXIS_TICK} interval="preserveStartEnd" stroke={chartColor('grid')} />
                  <YAxis tick={AXIS_TICK} tickFormatter={(v) => fmtMoney(v)} width={72} stroke={chartColor('grid')} />
                  <Tooltip
                    formatter={(v, name) => {
                      const lane = lanes.find((l) => String(l.employee_id) === name)
                      return [fmtMoney(v), lane?.name ?? name]
                    }}
                  />
                  <Legend
                    content={({ payload }) => (
                      <div className="race-line-legend">
                        {racers.map((r, i) => (
                          <span key={r.id} className="race-line-legend-item">
                            <span className="race-swatch" style={{ background: chartSeries(i) }} />
                            <Avatar user={{ name: r.lane.name, photo: r.lane.photo }} size="xs" />
                            {r.lane.name}
                          </span>
                        ))}
                      </div>
                    )}
                  />
                  {racers.map((r, i) => (
                    <Line
                      key={r.id}
                      type="monotone"
                      dataKey={r.id}
                      stroke={chartSeries(i)}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  ))}
                  {/* Avatar headmarkers at each line's final point. */}
                  {racers.map((r) => {
                    const last = raceRows[raceRows.length - 1]
                    if (!last) return null
                    return (
                      <ReferenceDot key={`head-${r.id}`} x={last.label} y={last[r.id]}
                        r={11} ifOverflow="extendDomain"
                        shape={(props) => <AvatarDot {...props} photo={r.lane.photo} name={r.lane.name} />}
                      />
                    )
                  })}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="race-standings">
            <h4 className="race-subtitle">Final standings</h4>
            <ol className="race-rows">
              {lanes.map((e, i) => (
                <li key={e.employee_id} className={`race-row${i === 0 ? ' race-row-leader' : ''}`}>
                  <span className={`race-rank race-rank-${i + 1}`}>{i + 1}</span>
                  <Avatar user={{ name: e.name, photo: e.photo }} size="sm" />
                  <span className="race-row-name">{e.name}</span>
                  <span className="race-row-bar" aria-hidden="true">
                    <span
                      className="race-row-fill"
                      style={{ width: `${Math.max(4, (e.value / maxVal) * 100)}%`, background: chartColor(metric) }}
                    />
                  </span>
                  <span className="race-row-value">{fmtMoney(e.value)}</span>
                  <span className="race-standing-figures">
                    <span>Rev <strong>{fmtMoney(e.revenue)}</strong> · Profit <strong>{fmtMoney(e.profit)}</strong></span>
                  </span>
                  <DeltaChip value={e.change_pct?.[metric]} label={`vs last ${data.period}`} />
                </li>
              ))}
            </ol>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Avatar "headmarker": renders the employee's photo at the end of
 * their race line. Uses Recharts' low-level shape API so we can draw
 * an <image> clipped to a circle at the (x, y) reference point.
 */
function AvatarDot({ cx, cy, photo, name }) {
  if (cx == null || cy == null) return null
  const r = 11
  const clipId = `avatar-clip-${name?.replace(/[^a-z0-9]/gi, '')}`
  return (
    <g>
      <clipPath id={clipId}>
        <circle cx={cx} cy={cy} r={r} />
      </clipPath>
      <circle cx={cx} cy={cy} r={r + 2} fill="#fff" stroke={chartColor('grid')} />
      {photo ? (
        <image
          href={photo}
          x={cx - r} y={cy - r} width={r * 2} height={r * 2}
          clipPath={`url(#${clipId})`}
          preserveAspectRatio="xMidYMid slice"
        />
      ) : (
        <text x={cx} y={cy + 4} textAnchor="middle" fontSize={11} fontWeight="700" fill="#fff">
          {name?.[0] ?? '?'}
        </text>
      )}
    </g>
  )
}
