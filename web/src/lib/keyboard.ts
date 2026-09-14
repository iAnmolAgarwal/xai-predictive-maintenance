/**
 * Roving-tabindex maths for the tile grid and the speed segmented control.
 * Pure functions, so the grid's keyboard behaviour is unit-testable without a
 * DOM.
 */

export type GridMove = 'left' | 'right' | 'up' | 'down' | 'home' | 'end';

const ARROW_TO_MOVE: ReadonlyMap<string, GridMove> = new Map([
  ['ArrowLeft', 'left'],
  ['ArrowRight', 'right'],
  ['ArrowUp', 'up'],
  ['ArrowDown', 'down'],
  ['Home', 'home'],
  ['End', 'end'],
]);

/** Map a keyboard event key to a grid move, or `null` if it is not one. */
export function gridMoveForKey(key: string): GridMove | null {
  return ARROW_TO_MOVE.get(key) ?? null;
}

/**
 * Next focus index in a `columns`-wide grid of `count` items. Horizontal moves
 * wrap within the row; vertical moves wrap within the column.
 */
export function nextGridIndex(
  index: number,
  move: GridMove,
  count: number,
  columns: number,
): number {
  if (count <= 0) return 0;
  const cols = Math.max(1, Math.min(columns, count));
  switch (move) {
    case 'home':
      return 0;
    case 'end':
      return count - 1;
    case 'left':
      return (index - 1 + count) % count;
    case 'right':
      return (index + 1) % count;
    case 'up': {
      const candidate = index - cols;
      return candidate >= 0 ? candidate : lastInColumn(index, count, cols);
    }
    case 'down': {
      const candidate = index + cols;
      return candidate < count ? candidate : index % cols;
    }
  }
}

function lastInColumn(index: number, count: number, cols: number): number {
  let candidate = index % cols;
  while (candidate + cols < count) candidate += cols;
  return candidate;
}

/** True for the two keys that must activate a non-native button surface. */
export function isActivationKey(key: string): boolean {
  return key === 'Enter' || key === ' ';
}
