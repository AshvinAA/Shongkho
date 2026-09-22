import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, LabelList, ReferenceDot, Legend,
} from 'recharts'
import { fmtMoney } from '../../utils/format.js'
import { DeltaChip } from './common.jsx'
import Avatar from '../Avatar.jsx'

const LINE_COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2']

/**
 * Employee race — Track A "employees" snapshot.
 *
 * Two visualizations from one frozen snapshot:
 *   1. Race over time (line chart): cumulative revenue/profit per
 *      employee across the period's buckets — avatars drift apart as
 *      the period progresses. Driven by `race_series` (string employee
 *      ids -> cumulative arrays aligned with `labels`).
 *   2. The bar race (kept from stage 1): final standings, per-person
 *      delta chips, hover tooltip with full context.
 *
 * metric switches BOTH charts between revenue and profit with no
 * refetch — both series ship inside the snapshot.
 */
export default function EmployeeRace({ data, metric = 'revenue' }) {
  if (!data?.employees) return null

  const lanes = data.employees
    .map((e) => ({ ...e, value: e[metric] ?? 0 }))
    .sort((a, b) => b.value - a.value)
  const leader = lanes[0]
  const rs = data.race_series

  // ---- race-over-time chart data ----
  // rows: [{ label, [id]: cumulativeValue, ... }, ...]
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
        <span className="muted">
          🏁 Leader: <strong>{leader?.name ?? '—'}</strong>
        </span>
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
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border, #e5e7eb)" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmtMoney(v)} width={72} />
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
                            <span className="race-swatch" style={{ background: colorOf(i) }} />
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
                      stroke={colorOf(i)}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  ))}
                  {/* Avatar headmarkers at each line's final point. */}
                  {racers.map((r, i) => {
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

          <div className="chart-wrap" style={{ marginTop: '0.75rem' }}>
            <h4 className="race-subtitle">Final standings</h4>
            <ResponsiveContainer width="100%" height={Math.max(150, lanes.length * 52)}>
              <BarChart data={lanes} layout="vertical" margin={{ top: 4, right: 64, bottom: 4, left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border, #e5e7eb)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => fmtMoney(v)} />
                <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(v) => fmtMoney(v)}
                  content={({ payload }) => {
                    if (!payload?.length) return null
                    const e = payload[0].payload
                    return (
                      <div className="race-tooltip">
                        <Avatar user={{ name: e.name, photo: e.photo }} size="xs" />
                        <strong>{e.name}</strong>
                        <div>{e.orders} order{e.orders === 1 ? '' : 's'} this {data.period}</div>
                        <div>Revenue {fmtMoney(e.revenue)} <DeltaChip value={e.change_pct?.revenue} /></div>
                        <div>Profit {fmtMoney(e.profit)} <DeltaChip value={e.change_pct?.profit} /></div>
                      </div>
                    )
                  }}
                />
                <Bar dataKey="value" fill="var(--primary, #2563eb)" radius={[0, 6, 6, 0]} barSize={24}>
                  <LabelList dataKey="value" position="right" formatter={(v) => fmtMoney(v)} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <ul className="race-legend">
            {lanes.map((e) => (
              <li key={e.employee_id}>
                <Avatar user={{ name: e.name, photo: e.photo }} size="sm" />
                <strong>{e.name}</strong>
                <span className="muted">{e.orders} order{e.orders === 1 ? '' : 's'}</span>
                <DeltaChip value={e.change_pct?.[metric]} label={`vs last ${data.period}`} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function colorOf(i) {
  return LINE_COLORS[i % LINE_COLORS.length]
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
      <circle cx={cx} cy={cy} r={r + 2} fill="#fff" stroke="var(--border, #e5e7eb)" />
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
