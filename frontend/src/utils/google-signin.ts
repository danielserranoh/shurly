// Phase 3.13.5 — Google sign-in. The API sends the browser to Google and back to
// /login/#code=… (or #error=…); the page trades the one-time code for a session by POST,
// so the JWT never travels in a URL.

import { API_BASE_URL, apiPost } from './api';
import { rememberNext } from './auth';
import type { LoginResponse } from './types';

export const GOOGLE_START_URL = `${API_BASE_URL}/api/v1/auth/google/start`;

/** Leave for Google; `next` is where to land once signed in. */
export function startGoogleSignIn(next: string | null | undefined): void {
  rememberNext(next);
  window.location.assign(GOOGLE_START_URL);
}

export const exchangeGoogleCode = (code: string) => apiPost<LoginResponse>('/api/v1/auth/google/exchange', { code }, false);

// The reasons of server/app/google_auth.py's docstring.
const MESSAGES = new Map<string, string>([
  ['state', 'That sign-in expired or began in another browser. Try again.'],
  ['denied', 'Google sign-in was cancelled. Try again when you’re ready.'],
  ['domain', 'Only accounts on your organization’s domain can sign in. Use your work Google account.'],
  ['unverified', 'Google hasn’t verified that account’s email address, so it can’t sign in.'],
  ['invalid_token', 'We couldn’t verify Google’s answer. Try again.'],
  ['account_conflict', 'That email’s Shurly account is linked to a different Google account. Ask an owner of your organization for help.'],
  ['inactive', 'That account has been closed. Ask an owner of your organization if you need it back.'],
  ['google_unavailable', 'Google sign-in isn’t available right now. Try again later, or log in with your password if you have one.'],
  ['try_again', 'Another sign-in to that account was finishing at the same moment. Try again.'],
  ['rate_limited', 'Too many sign-in attempts from your network. Wait a minute and try again.'],
]);

/** Human copy for the error codes the API sends back; an unknown code gets a general line. */
export function googleErrorMessage(code: string | null | undefined): string {
  return (code && MESSAGES.get(code)) || 'Google sign-in didn’t work. Try again.';
}
