import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, LabelList,
} from 'recharts'
import { fmtMoney } from '../../utils/format.js'
import { DeltaChip } from './common.jsx'

const COLOR = 'var(--primary, #2563eb)'

/**
 * Employee race — Track A "employees" snapshot.
 *
 * `data`: { employees: [{ employee_id, name, photo, orders, revenue,
 *   profit, change_pct: {revenue, profit, orders} }], period }
 *
 * Avatars ride each bar (your design: staff literally race each other).
 * metric picks which number the bars show — switching never refetches,
 * both metrics ship inside the snapshot.
 */
export default function EmployeeRace({ data, metric = 'revenue' }) {
  if (!data?.employees) return null

  const lanes = data.employees
    .map((e) => ({
      ...e,
      value: e[metric] ?? 0,
      // Shorten long names for the axis, keep full name in the avatar title.
      short: e.name.length > 12 ? `${e.name.slice(0, 11)}…` : e.name,
    }))
    .sort((a, b) => b.value - a.value)

  if (!lanes.length) {
    return <p className="muted">No employee sales recorded this {data.period} yet.</p>
  }

  const leader = lanes[0]

  return (
    <div className="analytics-panel">
      <div className="analytics-panel-head">
        <h3 className="card-title">Employee race — {metric}</h3>
        <span className="muted">
          🏁 {leader.photo ? 'Leader' : 'Leading'}: <strong>{leader.name}</strong>
        </span>
      </div>

      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={Math.max(160, lanes.length * 56)}>
          <BarChart data={lanes} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border, #e5e7eb)" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => fmtMoney(v)} />
            <YAxis type="category" dataKey="short" width={90} tick={{ fontSize: 12 }} />
            <Tooltip
              formatter={(v) => fmtMoney(v)}
              // Full context on hover: orders + both metrics + delta.
              content={({ payload }) => {
                if (!payload?.length) return null
                const e = payload[0].payload
                return (
                  <div className="race-tooltip">
                    <strong>{e.name}</strong>
                    <div>{e.orders} order{e.orders === 1 ? '' : 's'} this {data.period}</div>
                    <div>Revenue {fmtMoney(e.revenue)} <DeltaChip value={e.change_pct?.revenue} /></div>
                    <div>Profit {fmtMoney(e.profit)} <DeltaChip value={e.change_pct?.profit} /></div>
                  </div>
                )
              }}
            />
            <Bar dataKey="value" fill={COLOR} radius={[0, 6, 6, 0]} barSize={26}>
              <LabelList dataKey="value" position="right" formatter={(v) => fmtMoney(v)} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        {/* Avatars overlaid on the bars' right edge — the "racers". */}
        <div className="race-avatars" aria-hidden="true">
          {lanes.map((e, i) => (
            <div key={e.employee_id} className="race-avatar-row" style={{ height: `${100 / lanes.length}%` }}>
              <img
                className={`race-avatar${i === 0 ? ' race-avatar-lead' : ''}`}
                src={e.photo || undefined}
                alt=""
                title={e.name}
                onError={(ev) => { ev.currentTarget.style.visibility = 'hidden' }}
                data-fallback={e.name?.[0] ?? '?'}
              />
              {i === 0 && <span className="race-flag">🏁</span>}
            </div>
        ))}
        </div>
      </div>

      <ul className="race-legend">
        {lanes.map((e) => (
          <li key={e.employee_id}>
            <strong>{e.name}</strong>
            <span className="muted">{e.orders} order{e.orders === 1 ? '' : 's'}</span>
            <DeltaChip value={e.change_pct?.[metric]} label={`vs last ${data.period}`} />
          </li>
        ))}
      </ul>
    </div>
  )
}
