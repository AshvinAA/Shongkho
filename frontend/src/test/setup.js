import '@testing-library/jest-dom/vitest'

/**
 * Mock scrollIntoView (jsdom does not implement it, some components call it).
 */
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

/**
 * IntersectionObserver polyfill for jsdom — used by the Analytics page's
 * floating period bubble. A no-op observe (never fires) keeps the bubble
 * hidden in tests that don't drive it explicitly.
 */
if (typeof globalThis.IntersectionObserver === 'undefined') {
  class IntersectionObserver {
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.IntersectionObserver = IntersectionObserver
}

/**
 * ResizeObserver polyfill for jsdom — required by Recharts'
 * ResponsiveContainer (and most chart libraries). jsdom has no layout
 * engine, so a no-op that immediately "observes" is all we need.
 */
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserver {
    constructor(callback) {
      this.callback = callback
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserver
}

// Silence the "not wrapped in act(...)" noise from fire-and-forget effects.
const originalError = console.error
console.error = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('not wrapped in act')) return
  originalError(...args)
}
