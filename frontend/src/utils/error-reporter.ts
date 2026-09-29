// Phase 6.4 — browser errors reach the logs (the API: server/app/client_errors.py; what a report says:
// error-report.ts). BaseLayout installs it on every page, before the page's own scripts: an uncaught error, a rejected
// promise, or a CSP or Trusted Types block, which a <meta> policy can't report by itself, becomes a POST to
// /api/v1/client-errors. Five at most a page, each once.

import { API_BASE_URL } from './api';
import { getToken } from './auth';
import { cspMessage, describeReason, isForeign, report, reportGate, sourceOf, type ErrorReport } from './error-report';

const ENDPOINT = `${API_BASE_URL}/api/v1/client-errors`;

export function installErrorReporter(): void {
  const allow = reportGate();
  const send = (r: ErrorReport | null) => {
    if (!r || !allow(r)) return;
    const token = getToken();
    // fetch with keepalive rather than sendBeacon: a beacon can't carry the bearer token, and keepalive still lets the
    // report out when the page is leaving. JSON, which the API takes and no NUL survives (error-report.ts).
    void fetch(ENDPOINT, {
      method: 'POST',
      keepalive: true,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(r),
    }).catch(() => {
      // Nowhere left to tell.
    });
  };

  window.addEventListener('error', (e) => {
    if (isForeign(e.message ?? '', e.filename)) return;
    const message = e.error instanceof Error ? describeReason(e.error) : (e.message ?? '');
    send(report('error', message, sourceOf(e.filename, e.lineno, e.colno, location.origin), location.pathname));
  });
  window.addEventListener('unhandledrejection', (e) => {
    send(report('rejection', describeReason(e.reason), '', location.pathname));
  });
  document.addEventListener('securitypolicyviolation', (e) => {
    if (e.blockedURI.startsWith(ENDPOINT)) return; // its own report was the one blocked: don't go round
    const source = sourceOf(e.sourceFile, e.lineNumber, e.columnNumber, location.origin);
    send(report('csp', cspMessage(e.effectiveDirective, e.blockedURI), source, location.pathname));
  });
}
