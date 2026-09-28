// Authentication helpers. The JWT lives in localStorage; pages behind AppLayout
// are additionally guarded by an inline <head> script so no protected UI flashes.

export const TOKEN_KEY = 'shurly_auth_token';

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function getToken(): string | null {
  return typeof window === 'undefined' ? null : localStorage.getItem(TOKEN_KEY);
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

/**
 * Only same-site paths are post-login destinations. `next` comes from a link anyone can craft
 * (`?next=`) or from sessionStorage, so it's resolved the way the browser will resolve it rather
 * than judged by its first characters: browsers drop tabs and line breaks ("/\t/evil.com" is
 * "//evil.com"), and dot segments can leave a path that starts with "//" ("/.//evil.com").
 * `origin` is for the tests (tests/auth.test.mjs).
 */
export function safeNext(next: string | null | undefined, fallback = '/dashboard/', origin = window.location.origin): string {
  // No control characters or backslashes in a path of ours: refused outright, rather than
  // guessing how each browser rewrites them.
  if (!next || !next.startsWith('/') || /[\x00-\x1f\x7f\\]/.test(next)) return fallback;
  let url: URL;
  try {
    url = new URL(next, origin);
  } catch {
    return fallback;
  }
  const path = url.pathname + url.search + url.hash;
  return url.origin === origin && !path.startsWith('//') ? path : fallback;
}

const NEXT_KEY = 'shurly_next';

/**
 * Remember where to land after signing in. The round trip through Google can't carry it:
 * /auth/google/start takes no `next`, on purpose (that's how open redirects happen).
 */
export function rememberNext(path: string | null | undefined): void {
  sessionStorage.setItem(NEXT_KEY, safeNext(path));
}

/** The remembered landing page, used once, and only if it's a same-site relative path. */
export function takeNext(fallback = '/dashboard/'): string {
  const stored = sessionStorage.getItem(NEXT_KEY);
  sessionStorage.removeItem(NEXT_KEY);
  return safeNext(stored, fallback);
}

/** Send the user to /login, remembering where they were. */
export function redirectToLogin(reason?: 'expired'): void {
  const here = window.location.pathname + window.location.search;
  const params = new URLSearchParams({ next: here });
  if (reason) params.set('reason', reason);
  window.location.replace(`/login/?${params.toString()}`);
}

export function logout(): void {
  removeToken();
  window.location.href = '/login/?reason=signed-out';
}

export function requireAuth(): void {
  if (!isAuthenticated()) redirectToLogin();
}
