/**
 * Protik's mark — the advisor's "face" everywhere.
 *
 * A deep-teal rounded tile carrying the Bengali letter প (Protik's
 * initial, set in Noto Sans Bengali) with a small amber spark in the
 * corner — the "insight glint". Pure SVG painted from design tokens,
 * so it re-themes with the palette and stays crisp at any size.
 *
 *   <ProtikMark size={28} />   sidebar icon, advisor avatar, sparkles
 */
export default function ProtikMark({ size = 28, className = '', ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label="Protik"
      className={`protik-mark ${className}`}
      focusable="false"
      {...rest}
    >
      <rect x="1" y="1" width="30" height="30" rx="9" className="protik-mark-bg" />
      <text
        x="14.5"
        y="22.5"
        textAnchor="middle"
        fontSize="17"
        fontWeight="700"
        className="protik-mark-glyph"
      >
        প
      </text>
      <circle cx="24.5" cy="8.5" r="2.6" className="protik-mark-spark" />
    </svg>
  )
}
