/**
 * Overlays: Modal (centered dialog) and Drawer (side sheet for edit forms).
 * Both close on Escape + backdrop click and lock body scroll while open.
 */
import { useEffect } from 'react'
import { X } from 'lucide-react'

function useOverlayLock(open, onClose) {
  useEffect(() => {
    if (!open) return undefined
    function onKeyDown(e) {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKeyDown)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = ''
    }
  }, [open, onClose])
}

/** Centered modal dialog. */
export function Modal({ open, title, onClose, children, footer, width }) {
  useOverlayLock(open, onClose)
  if (!open) return null

  return (
    <div className="ui-overlay-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="ui-modal" role="dialog" aria-modal="true" aria-label={title} style={width ? { maxWidth: width } : undefined}>
        <div className="ui-overlay-header">
          <h3 className="ui-overlay-title">{title}</h3>
          <button type="button" className="ui-overlay-close" aria-label="Close" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="ui-overlay-body">{children}</div>
        {footer ? <div className="ui-overlay-footer">{footer}</div> : null}
      </div>
    </div>
  )
}

/** Right-side drawer sheet — used for edit/invite forms and detail views. */
export function Drawer({ open, title, onClose, children, footer }) {
  useOverlayLock(open, onClose)
  if (!open) return null

  return (
    <div className="ui-overlay-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <aside className="ui-drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="ui-overlay-header">
          <h3 className="ui-overlay-title">{title}</h3>
          <button type="button" className="ui-overlay-close" aria-label="Close" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="ui-overlay-body">{children}</div>
        {footer ? <div className="ui-overlay-footer">{footer}</div> : null}
      </aside>
    </div>
  )
}
