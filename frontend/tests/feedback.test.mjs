// "Send feedback" (src/utils/feedback.ts): an email to the team, from the page it was sent from, by its path only.
// Run: `npm test`.

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { feedbackHref } from '../src/utils/feedback.ts';

const mail = (href) => new URL(href);

test('an email to the address, with its subject', () => {
  const href = feedbackHref('support@griddo.io', '/dashboard/');
  assert.equal(mail(href).protocol, 'mailto:');
  assert.equal(mail(href).pathname, 'support@griddo.io');
  assert.equal(mail(href).searchParams.get('subject'), 'Shurly feedback');
  assert.match(href, /subject=Shurly%20feedback/); // %20, not +: mail apps read + as a plus
});

test("the page it came from, by its path: never a query or a fragment", () => {
  const body = mail(feedbackHref('support@griddo.io', '/dashboard/link/?code=abc123&domain=go.griddo.io#visits')).searchParams.get('body');
  assert.equal(body, '\r\n\r\nPage: /dashboard/link/');
});

test('line breaks as mail wants them (RFC 6068)', () => {
  assert.match(feedbackHref('support@griddo.io', '/'), /body=%0D%0A%0D%0APage%3A%20%2F$/);
});
