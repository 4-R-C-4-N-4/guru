/**
 * deck-softlock.test.ts (todo:1265031d)
 *
 * Source-shape regression for the empty-state softlock: after an apply,
 * skipped rows re-enter the pending pool behind the saved resume cursor;
 * every deck's empty state must detect remainingInFilter > 0 and offer a
 * Start-from-top reset that clears the saved cursor and refetches. First
 * web test in this package — rendering the decks needs router + fetch
 * scaffolding; the source contract is what regressed-by-omission before.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const DECKS: Array<{ file: string; cursorReset: RegExp }> = [
  { file: 'Deck.tsx', cursorReset: /saveCursor\(filters, null\)/ },
  { file: 'EdgeDeck.tsx', cursorReset: /saveEdgeCursor\(filters, null\)/ },
  { file: 'CleanupDeck.tsx', cursorReset: /saveCleanupCursor\(filters, null\)/ },
];

describe.each(DECKS)('$file empty state', ({ file, cursorReset }) => {
  const src = readFileSync(join(__dirname, file), 'utf8');
  // The empty-state branch is everything after the !state.current guard.
  const empty = src.slice(src.indexOf('if (!state.current)'));

  it('offers Start from top when rows remain behind the cursor', () => {
    expect(empty).toMatch(/state\.remainingInFilter > 0/);
    expect(empty).toMatch(/Start from top/);
  });

  it('the reset clears the saved cursor and refetches from the top', () => {
    const resetIdx = empty.indexOf('Start from top');
    const around = empty.slice(Math.max(0, resetIdx - 800), resetIdx);
    expect(around).toMatch(cursorReset);
    expect(around).toMatch(/fetchPage\(null\)/);
  });
});
