/**
 * Shared chart palette (design system v2).
 *
 * Recharts needs concrete color strings, but our colors live in CSS
 * custom properties so the whole product rebrands from one place.
 * These helpers resolve a token once (getComputedStyle) and cache it —
 * SVG attributes cannot read var() reliably across all browsers.
 *
 * Usage:
 *   stroke={chartColor('revenue')}
 *   stroke={chartSeries(i)}        // categorical series 1..6
 *
 * clearChartColorCache() exists for tests/theme swaps; components never
 * need it in normal app life (tokens don't change at runtime).
 */

let cache = {}

function resolve(varName, fallback) {
  if (cache[varName]) return cache[varName]
  let value = fallback
  try {
    const raw = getComputedStyle(document.documentElement)
      .getPropertyValue(varName)
      .trim()
    if (raw) value = raw
  } catch {
    /* jsdom / SSR: keep the fallback */
  }
  cache[varName] = value
  return value
}

/** Semantic data colors — same meaning in every chart. */
export function chartColor(name) {
  return resolve(`--chart-${name}`, {
    revenue: '#1f7263',
    profit: '#2f855a',
    orders: '#b45309',
    neutral: '#5c6f68',
    grid: '#e3efe9',
    axis: '#5c6f68',
  }[name] || '#2a8d78')
}

/** Categorical series colors — distinct hues at AA contrast on white. */
export function chartSeries(index) {
  return resolve(`--chart-series-${(Math.abs(index) % 6) + 1}`, '#2a8d78')
}

export function clearChartColorCache() {
  cache = {}
}
