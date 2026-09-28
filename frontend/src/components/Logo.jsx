/**
 * Shongkho logo — the single brand mark for the whole app.
 *
 * The mark: a deep-teal tile carrying two linked rings — the product and
 * the payment joined by every sale (and a quiet nod to the Bengali ৮,
 * from "সংখ্যা", the number). Pure SVG painted from design tokens, so
 * it re-themes with the palette and stays crisp at any size.
 *
 *   <Logo />            — mark only (sidebar, collapsed rail)
 *   <Logo name />       — mark + wordmark (topbar, auth pages)
 *   <Logo size={52} />  — scale freely
 */
export default function Logo({ size = 28, name = false, className = '' }) {
  return (
    <span className={`shk-logo ${className}`}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        role="img"
        aria-label="Shongkho logo"
        focusable="false"
      >
        <rect x="1" y="1" width="30" height="30" rx="8" className="shk-logo-bg" />
        <circle cx="12.5" cy="12" r="5.5" className="shk-logo-ring" />
        <circle cx="19.5" cy="20" r="5.5" className="shk-logo-ring" />
      </svg>
      {name ? <span className="shk-logo-name">Shongkho</span> : null}
    </span>
  )
}
