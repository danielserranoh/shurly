// 3.10.8 — "Typos & broken links" asks only for what a person could have mistyped (`typos_only`): vulnerability
// scanners' probes and bots are left out, and the API says how many hits that was. The line under the list.

const number = new Intl.NumberFormat('en-US'); // formatNumber's, without its imports: node --test runs this file

export interface HiddenHitsNote {
  text: string;
  /** The button's label: what it does. */
  action: 'Show them' | 'Hide them';
}

/**
 * What the line says, `null` when it says nothing: how many hits from scanners and bots aren't shown, or, once
 * they are, that they are.
 */
export function hiddenHitsNote(hiddenVisits: number, showingThem: boolean): HiddenHitsNote | null {
  if (showingThem) return { text: 'Hits from scanners and bots are shown too.', action: 'Hide them' };
  if (hiddenVisits <= 0) return null;
  const hits = hiddenVisits === 1 ? '1 hit' : `${number.format(hiddenVisits)} hits`;
  return { text: `${hits} from scanners and bots ${hiddenVisits === 1 ? 'isn’t' : 'aren’t'} shown.`, action: 'Show them' };
}
