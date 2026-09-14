/**
 * Feature registration (frontend.md §2, "Cross-task integration points").
 *
 * Written once, in Phase 3, and never edited again: `import.meta.glob` eagerly
 * imports every `web/src/features/<name>/index.ts` for its side effects, which is
 * where each Phase-4 task calls `registerSlot`. Adding a feature directory is
 * therefore the whole integration step — no shell file changes, no merge
 * conflict between parallel tasks, and no import of a module that does not exist
 * yet. Slots nobody has registered for render their designed empty state.
 */
const modules = import.meta.glob('./*/index.ts', { eager: true });

/** The feature module paths that registered themselves, for diagnostics. */
export const registeredFeatureModules: string[] = Object.keys(modules).sort();
