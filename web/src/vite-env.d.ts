/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Only `pnpm dev:mock` / `pnpm build:mock` set this. Never set in Docker. */
  readonly VITE_USE_MOCKS?: string;
  /** Enables the `epm:commit` performance marks the perf spec measures. */
  readonly VITE_PERF?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
