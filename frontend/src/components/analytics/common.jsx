/**
 * Small shared controls for the Analytics page.
 *
 * SegmentedControl — the day/week/month + revenue/profit switcher.
 * DeltaChip        — the "+12.5% vs last week" indicator (green/red/neutral).
 */
export function SegmentedControl({ options, value, onChange, disabled = false }) {
  return (
    <div className={`segmented${disabled ? ' segmented-disabled' : ''}`} role="tablist">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          aria-selected={value === opt.value}
          disabled={disabled}
          className={`segmented-btn${value === opt.value ? ' segmented-active' : ''}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export function DeltaChip({ value, label }) {
  if (value === null || value === undefined) {
    return (
      <span className="delta-chip delta-neutral" title="No data to compare against">
        {label ? `— ${label}` : '— no comparison'}
      </span>
    )
  }
  const cls = value > 0 ? 'delta-up' : value < 0 ? 'delta-down' : 'delta-neutral'
  const arrow = value > 0 ? '▲' : value < 0 ? '▼' : '▬'
  const text = `${arrow} ${Math.abs(value)}%`
  return (
    <span className={`delta-chip ${cls}`} title="Change vs the previous period">
      {text}
      {label ? <span className="delta-label"> {label}</span> : null}
    </span>
  )
}

export default { SegmentedControl, DeltaChip }
