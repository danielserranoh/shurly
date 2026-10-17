// Phase 6.3 — every inline script in the site. They run before the page paints, so they can't
// be bundled; the Content-Security-Policy allows them by the hash of these exact strings
// (astro.config.mjs → security.csp), so the page and the policy can't drift. A new inline
// script goes here too: scripts/check-csp.mjs fails the build on one the policy doesn't cover.
// Behaviour of the guards tested in tests/csp.test.mjs.

/** Pages behind login (BaseLayout): without a session, to /login/ with the way back, before anything shows. */
export const PROTECTED_GUARD =
  "if (!localStorage.getItem('shurly_auth_token')) location.replace('/login/?next=' + encodeURIComponent(location.pathname + location.search));";

/**
 * Sign-in pages (BaseLayout): with a session, straight to the dashboard. Google's answer
 * (#code=… or #error=…) is for the page even then: that new sign-in replaces the session,
 * as when someone signs in again to set a password.
 */
export const GUEST_GUARD =
  "if (localStorage.getItem('shurly_auth_token') && !/^#(code|error)=/.test(location.hash)) location.replace('/dashboard/');";

/**
 * Settings: open the tab the address names (#api, #tags…) before the page paints. The organization has its own
 * page since 3.14.7: an old link to #organization goes there, its query kept.
 */
export const SETTINGS_TAB_FROM_HASH = `(function () {
  var key = location.hash.slice(1).toLowerCase();
  if (key === 'organization') return location.replace('/dashboard/organization/' + location.search);
  var tab = document.getElementById('tab-' + key);
  if (!tab || tab.getAttribute('role') !== 'tab') return;
  document.querySelectorAll('[data-tablist] [role="tab"]').forEach(function (t) {
    var on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
  });
})();`;

/** What the policy allows (astro.config.mjs hashes each). */
export const INLINE_SCRIPTS = [PROTECTED_GUARD, GUEST_GUARD, SETTINGS_TAB_FROM_HASH];
