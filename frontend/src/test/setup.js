import '@testing-library/jest-dom/vitest'

/**
 * Mock scrollIntoView (jsdom does not implement it, some components call it).
 */
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

// Silence the "not wrapped in act(...)" noise from fire-and-forget effects.
const originalError = console.error
console.error = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('not wrapped in act')) return
  originalError(...args)
}
