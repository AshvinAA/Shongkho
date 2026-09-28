import { cloneElement, isValidElement, useId } from 'react'

/**
 * Field wrapper: label + control + hint/error text.
 *
 *   <Field label="Product name" hint="Shown on receipts">
 *     <Input value={…} onChange={…} />
 *   </Field>
 *
 * The single child control is auto-wired with id / aria-invalid /
 * aria-describedby for accessibility.
 */
export function Field({ label, hint, error, children, className = '' }) {
  const id = useId()
  const child = isValidElement(children) ? children : null
  const control = child
    ? {
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': error || hint ? `${id}-desc` : undefined,
      }
    : {}

  return (
    <label className={`ui-field ${className}`}>
      <span className="ui-field-label">{label}</span>
      {child ? cloneElement(child, control) : children}
      {error || hint ? (
        <span id={`${id}-desc`} className={`ui-field-desc ${error ? 'ui-field-error' : ''}`}>
          {error || hint}
        </span>
      ) : null}
    </label>
  )
}

/** Text input primitive. */
export function Input({ className = '', invalid = false, ...rest }) {
  return <input className={`ui-input ${invalid ? 'ui-input-invalid' : ''} ${className}`} {...rest} />
}

/** Select primitive. */
export function Select({ className = '', invalid = false, children, ...rest }) {
  return (
    <select className={`ui-select ${invalid ? 'ui-input-invalid' : ''} ${className}`} {...rest}>
      {children}
    </select>
  )
}

/** Multiline textarea primitive. */
export function Textarea({ className = '', invalid = false, ...rest }) {
  return <textarea className={`ui-input ui-textarea ${invalid ? 'ui-input-invalid' : ''} ${className}`} {...rest} />
}
