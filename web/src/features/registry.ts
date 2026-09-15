/**
 * Feature registration (frontend.md §2, "Cross-task integration points").
 *
 * Written once, in Phase 3, and never edited again: `import.meta.glob` eagerly
 * imports every `web/src/features/<name>/index.ts` for its side effects, which is
 * where each Phase-4 task calls `registerSlot`. Adding a feature directory is
 * therefore the whole integration step — no shell file changes, no merge
 * conflict between parallel tasks, and no import of a module that does not exist
 * yet. Slots nobody has registered for render their designed empty state.
 *
 * **Binding constraint on Phase-4 tasks:** because the glob is eager, a feature's
 * `index.ts` is in the entry chunk. Keep it a thin registration module that
 * `React.lazy`s its component — `registerSlot('detail.shap', lazy(() =>
 * import('./ShapPanel')))` — so the route-level code splitting §4.5 requires
 * still happens and uPlot, the D3 subset and the SHAP views stay out of the
 * initial bundle.
 */
const modules = import.meta.glob('./*/index.ts', { eager: true });

/** The feature module paths that registered themselves, for diagnostics. */
export const registeredFeatureModules: string[] = Object.keys(modules).sort();
