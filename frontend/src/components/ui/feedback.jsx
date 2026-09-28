/**
 * Feedback & display primitives: Card, Badge, DeltaChip, StatCard,
 * Skeleton, EmptyState, ErrorState, Toast, Avatar.
 *
 * Tokens only (docs/UI_AUDIT.md §6). DeltaChip never uses color alone —
 * every delta ships with an explicit ▲/▼/▬ marker.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, X, RefreshCw, Inbox } from 'lucide-react'
import AvatarBase from '../Avatar.jsx'

let toastSeq = 0

/** Surface primitive — white card, 1px border, radius-lg. */
export function Card({ className = '', children, ...rest }) {
  return (
    <section className={`ui-card ${className}`} {...rest}>
      {children}
    </section>
  )
}

/** Card header row: title + optional actions on the right. */
export function CardHeader({ title, subtitle, actions, className = '' }) {
  return (
    <div className={`ui-card-header ${className}`}>
      <div className="ui-card-heading">
        <h3 className="ui-card-title">{title}</h3>
        {subtitle ? <p className="ui-card-subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="ui-card-actions">{actions}</div> : null}
    </div>
  )
}

/**
 * Badge. variant: neutral | brand | success | warning | danger | outline.
 */
export function Badge({ variant = 'neutral', className = '', children }) {
  return <span className={`ui-badge ui-badge-${variant} ${className}`}>{children}</span>
}

/**
 * Delta indicator. value: number (percent) | null | undefined.
 * Always pairs the marker (▲/▼/▬) with the semantic tint.
 */
export function DeltaChip({ value, label }) {
  if (value === null || value === undefined) {
    return (
      <span className="ui-delta ui-delta-neutral" title="No data to compare against">
        {'▬ '}
        {label ? `— ${label}` : '— no comparison'}
      </span>
    )
  }
  const cls = value > 0 ? 'ui-delta-up' : value < 0 ? 'ui-delta-down' : 'ui-delta-neutral'
  const marker = value > 0 ? '▲' : value < 0 ? '▼' : '▬'
  return (
    <span className={`ui-delta ${cls}`} title="Change vs the previous period">
      {`${marker} ${Math.abs(value)}%`}
      {label ? <span className="ui-delta-label"> {label}</span> : null}
    </span>
  )
}

/**
 * KPI stat card: label (uppercase muted), headline number (tabular, large),
 * optional delta chip, optional sparkline node, muted supporting detail.
 */
export function StatCard({ label, value, delta, detail, sparkline, tone, loading = false, className = '' }) {
  if (loading) {
    return (
      <div className={`ui-stat ui-stat-loading ${className}`}>
        <Skeleton width="40%" height="0.75rem" />
        <Skeleton width="70%" height="2rem" />
        <Skeleton width="50%" height="0.75rem" />
      </div>
    )
  }
  return (
    <div className={`ui-stat ${tone ? `ui-stat-${tone}` : ''} ${className}`}>
      <span className="ui-stat-label">{label}</span>
      <span className="ui-stat-value">{value}</span>
      {delta !== undefined ? <DeltaChip value={delta} /> : null}
      {sparkline}
      {detail ? <span className="ui-stat-detail">{detail}</span> : null}
    </div>
  )
}

/** Loading placeholder. */
export function Skeleton({ width = '100%', height = '1rem', className = '' }) {
  return <span className={`ui-skeleton ${className}`} style={{ width, height }} aria-hidden="true" />
}

/** Empty state: icon + title + prose (+ optional action node). */
export function EmptyState({ icon: Icon = Inbox, title, children, action, className = '' }) {
  return (
    <div className={`ui-empty ${className}`}>
      {Icon ? <Icon className="ui-empty-icon" size={28} aria-hidden="true" /> : null}
      <h4 className="ui-empty-title">{title}</h4>
      {children ? <p className="ui-empty-body">{children}</p> : null}
      {action ? <div className="ui-empty-action">{action}</div> : null}
    </div>
  )
}

/** Error state with an optional retry action. */
export function ErrorState({ title = 'Something went wrong', children, onRetry, retryLabel = 'Try again', className = '' }) {
  return (
    <div className={`ui-error ${className}`} role="alert">
      <AlertTriangle className="ui-error-icon" size={28} aria-hidden="true" />
      <h4 className="ui-error-title">{title}</h4>
      {children ? <p className="ui-error-body">{children}</p> : null}
      {onRetry ? (
        <button type="button" className="ui-btn ui-btn-secondary ui-btn-sm" onClick={onRetry}>
          <RefreshCw size={14} aria-hidden="true" /> {retryLabel}
        </button>
      ) : null}
    </div>
  )
}

/**
 * Toast host + hook. Mount <ToastProvider /> once per layout; call
 * showToast via the context. Auto-dismisses after `duration` ms.
 */
const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const showToast = useCallback(
    ({ variant = 'info', title, body, duration = 4000 }) => {
      const id = ++toastSeq
      setToasts((ts) => [...ts, { id, variant, title, body }])
      if (duration > 0) {
        setTimeout(() => {
          setToasts((ts) => ts.filter((t) => t.id !== id))
        }, duration)
      }
      return id
    },
    [],
  )

  const dismiss = useCallback((id) => {
    setToasts((ts) => ts.filter((t) => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={showToast}>
      {children}
      <div className="ui-toast-host" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`ui-toast ui-toast-${t.variant}`}>
            {t.variant === 'success' ? (
              <CheckCircle2 size={18} aria-hidden="true" />
            ) : t.variant === 'error' ? (
              <AlertTriangle size={18} aria-hidden="true" />
            ) : t.variant === 'warning' ? (
              <AlertTriangle size={18} aria-hidden="true" />
            ) : (
              <Info size={18} aria-hidden="true" />
            )}
            <div className="ui-toast-text">
              {t.title ? <strong>{t.title}</strong> : null}
              {t.body ? <span>{t.body}</span> : null}
            </div>
            <button type="button" className="ui-toast-close" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const showToast = useContext(ToastContext)
  if (!showToast) {
    throw new Error('useToast must be used inside <ToastProvider>')
  }
  return { showToast }
}

/** Avatar re-export (wraps the existing component for one import path). */
export function Avatar(props) {
  return <AvatarBase {...props} />
}
