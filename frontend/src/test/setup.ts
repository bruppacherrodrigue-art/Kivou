import '@testing-library/jest-dom/vitest'

// Radix mesure certains contrôles de la référence avec ResizeObserver. jsdom
// ne l'implémente pas ; ce no-op reproduit seulement sa présence navigateur.
class TestResizeObserver implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
  configurable: true,
  writable: true,
  value: TestResizeObserver,
})
