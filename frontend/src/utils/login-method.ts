// The login page's password block (3.13.7). Accounts come from signing in with Google, so the password form waits
// behind a disclosure, closed, unless the address asks for it or the person chose it earlier this session.

/** sessionStorage: the password block was open when last left, in this tab. */
export const PASSWORD_CHOSEN_KEY = 'shurly_login_password';

/**
 * Whether the address asks for the password form: `?method=password`, `#password`, or an `?email=` to fill in,
 * since that field is in the block.
 */
export function asksForPassword(search: string, hash: string): boolean {
  const params = new URLSearchParams(search);
  return params.get('method') === 'password' || hash === '#password' || Boolean(params.get('email'));
}

/** Storage comes through a getter: reading `sessionStorage` itself throws when site data is blocked. */
type StorageGetter = () => Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** Whether the person opened the password block earlier this session. */
export function passwordChosen(storage: StorageGetter): boolean {
  try {
    return storage().getItem(PASSWORD_CHOSEN_KEY) === '1';
  } catch {
    return false;
  }
}

/** Keep the block's state for the session: open is remembered, closed forgets it. */
export function rememberPasswordChoice(storage: StorageGetter, open: boolean): void {
  try {
    if (open) storage().setItem(PASSWORD_CHOSEN_KEY, '1');
    else storage().removeItem(PASSWORD_CHOSEN_KEY);
  } catch {
    // No storage (a private window, blocked site data): the block just starts closed next time.
  }
}
