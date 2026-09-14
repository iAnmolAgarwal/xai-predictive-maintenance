import { describe, expect, it } from 'vitest';
import { gridMoveForKey, isActivationKey, nextGridIndex } from '../keyboard';

describe('gridMoveForKey', () => {
  it('maps the arrow, Home and End keys', () => {
    expect(gridMoveForKey('ArrowLeft')).toBe('left');
    expect(gridMoveForKey('ArrowRight')).toBe('right');
    expect(gridMoveForKey('ArrowUp')).toBe('up');
    expect(gridMoveForKey('ArrowDown')).toBe('down');
    expect(gridMoveForKey('Home')).toBe('home');
    expect(gridMoveForKey('End')).toBe('end');
  });

  it('ignores everything else', () => {
    expect(gridMoveForKey('a')).toBeNull();
  });
});

describe('nextGridIndex', () => {
  const count = 12;
  const columns = 4;

  it('wraps horizontally', () => {
    expect(nextGridIndex(0, 'left', count, columns)).toBe(11);
    expect(nextGridIndex(11, 'right', count, columns)).toBe(0);
  });

  it('wraps vertically within the column', () => {
    expect(nextGridIndex(0, 'up', count, columns)).toBe(8);
    expect(nextGridIndex(8, 'down', count, columns)).toBe(0);
    expect(nextGridIndex(4, 'up', count, columns)).toBe(0);
    expect(nextGridIndex(4, 'down', count, columns)).toBe(8);
  });

  it('jumps to the ends', () => {
    expect(nextGridIndex(5, 'home', count, columns)).toBe(0);
    expect(nextGridIndex(5, 'end', count, columns)).toBe(11);
  });

  it('is safe for an empty or single-row grid', () => {
    expect(nextGridIndex(0, 'right', 0, columns)).toBe(0);
    expect(nextGridIndex(0, 'down', 4, 4)).toBe(0);
  });
});

describe('isActivationKey', () => {
  it('accepts Enter and Space only', () => {
    expect(isActivationKey('Enter')).toBe(true);
    expect(isActivationKey(' ')).toBe(true);
    expect(isActivationKey('Tab')).toBe(false);
  });
});
