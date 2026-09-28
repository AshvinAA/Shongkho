/**
 * Selection controls: SegmentedControl and Tabs.
 *
 * SegmentedControl — compact either/or switcher (period, metric).
 * Tabs             — panel switcher with roving arrow-key focus.
 */
import { useRef } from 'react'

/** Controlled segmented control (role=tablist, arrow-key navigable). */
export function SegmentedControl({ options, value, onChange, disabled = false, ariaLabel, size = 'md', className = '' }) {
  return (
    <div
      className={`ui-segmented ui-segmented-${size} ${disabled ? 'ui-segmented-disabled' : ''} ${className}`}
      role="tablist"
      aria-label={ariaLabel}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          aria-selected={value === opt.value}
          disabled={disabled}
          className={`ui-segmented-btn${value === opt.value ? ' ui-segmented-active' : ''}`}
          onClick={() => onChange?.(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

/**
 * Tabs (aria-current pattern with arrow-key roving focus).
 *
 *   <Tabs
 *     tabs={[{ id: 'details', label: 'Details', icon: Info }]}
 *     active="details"
 *     onChange={setActive}
 *   />
 */
export function Tabs({ tabs, active, onChange, ariaLabel, className = '' }) {
  const listRef = useRef(null)

  function onKeyDown(e) {
    if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return
    e.preventDefault()
    const idx = tabs.findIndex((t) => t.id === active)
    const dir = e.key === 'ArrowRight' ? 1 : -1
    const next = tabs[(idx + dir + tabs.length) % tabs.length]
    onChange?.(next.id)
    const btn = listRef.current?.querySelector(`[data-tab-id="${CSS.escape(next.id)}"]`)
    btn?.focus()
  }

  return (
    <div className={`ui-tabs ${className}`} role="tablist" aria-label={ariaLabel} onKeyDown={onKeyDown} ref={listRef}>
      {tabs.map((tab) => {
        const Icon = tab.icon
        const isActive = tab.id === active
        return (
          <button
            key={tab.id}
            type="button"
            data-tab-id={tab.id}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            className={`ui-tab${isActive ? ' ui-tab-active' : ''}`}
            onClick={() => onChange?.(tab.id)}
          >
            {Icon ? <Icon size={15} aria-hidden="true" /> : null}
            {tab.label}
            {tab.badge !== undefined && tab.badge !== null ? <span className="ui-tab-badge">{tab.badge}</span> : null}
          </button>
        )
      })}
    </div>
  )
}
