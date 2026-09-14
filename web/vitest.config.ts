import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./vitest.setup.ts'],
    css: true,
    // Component tests live under src/; e2e/ belongs to Playwright. `test.exclude`
    // stays at its default, so src/mock/** is excluded from coverage
    // instrumentation only and `no-mock-in-prod` always runs (frontend.md §1.1).
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/contracts/**',
        'src/mock/**',
        'src/main.tsx',
        'src/vite-env.d.ts',
        'src/**/*.d.ts',
        'src/**/__tests__/**',
      ],
      thresholds: {
        autoUpdate: false,
        statements: 85,
        branches: 78,
        functions: 85,
        lines: 85,
        'src/{store,lib}/**': { statements: 90, lines: 90 },
        'src/shell/ws/**': { statements: 90, lines: 90 },
        'src/features/**': { statements: 80, lines: 80 },
      },
    },
  },
});
