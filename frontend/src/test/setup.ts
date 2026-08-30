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

// Le primitive Sidebar de la source normative interroge matchMedia au
// montage. jsdom ne le fournit pas ; le repli desktop garde les tests unitaires
// déterministes, tandis que les contrats mobiles installent leur propre stub.
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => true,
    }),
  })
}
