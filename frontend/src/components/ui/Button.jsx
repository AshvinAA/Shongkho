import { Loader2 } from 'lucide-react'

/**
 * Button primitive.
 *
 *   variant: primary | secondary | ghost | danger   (default primary)
 *   size:    sm | md | lg | xl                       (default md; xl = 56px, POS Charge)
 *   loading: shows a spinner and disables interaction
 *   icon:    optional leading icon (lucide component)
 *
 * All visual states (hover / focus-visible / disabled / loading) live here —
 * screens must not restyle buttons ad hoc.
 */
const VARIANT_CLASS = {
  primary: 'ui-btn-primary',
  secondary: 'ui-btn-secondary',
  ghost: 'ui-btn-ghost',
  danger: 'ui-btn-danger',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled = false,
  icon: Icon,
  type = 'button',
  className = '',
  children,
  ...rest
}) {
  const classes = [
    'ui-btn',
    VARIANT_CLASS[variant] || VARIANT_CLASS.primary,
    `ui-btn-${size}`,
    loading ? 'ui-btn-loading' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button type={type} className={classes} disabled={disabled || loading} {...rest}>
      {loading ? <Loader2 className="ui-btn-spinner" size={size === 'xl' ? 22 : 16} aria-hidden="true" /> : null}
      {!loading && Icon ? <Icon size={size === 'xl' ? 20 : 16} aria-hidden="true" /> : null}
      {children}
    </button>
  )
}
