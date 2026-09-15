import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The browser only ever sees one origin: dev proxies /api and /ws to the API
// container, and nginx.conf proxies the identical paths in production. No CORS
// story, no ws:// mixed-content story, identical URL shapes in both modes.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000';

// The MSW service worker lives in mock-public/ and is copied into the bundle
// only by `dev:mock` / `build:mock`. The default build has no static assets to
// copy at all -- fonts, styles and the worker are either bundled or mock-only --
// so `publicDir` is disabled and dist/ cannot contain a registerable worker.
const useMocks = process.env.VITE_USE_MOCKS === 'true';

export default defineConfig({
  plugins: [react()],
  publicDir: useMocks ? 'mock-public' : false,
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws': { target: apiTarget, ws: true, changeOrigin: true },
    },
  },
  preview: { port: 4173, strictPort: true },
  build: {
    target: 'es2022',
    sourcemap: false,
    // uPlot and the d3 maths subset are shared by every chart surface, so they
    // are split out of the entry chunk and cached across route chunks.
    rollupOptions: {
      output: {
        // Function form, so a chunk is only created when something actually
        // imports the library — no empty chunks before the chart features land.
        manualChunks(id: string) {
          if (id.includes('node_modules/uplot')) return 'uplot';
          if (/node_modules\/d3-/.test(id)) return 'd3';
          return undefined;
        },
      },
    },
  },
});
