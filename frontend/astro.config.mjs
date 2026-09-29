import { createHash } from 'node:crypto';
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import { mcpUrl } from './src/content/placeholders.mjs';
import { INLINE_SCRIPTS } from './src/inline-scripts.mjs';

// Phase 5.9 — one value for the manual's Markdown and for the app's scripts.
const MCP_URL = mcpUrl(process.env);

// Phase 6.3 — the API the pages call: the same origin in production, localhost:8000 by default.
const API_ORIGIN = new URL(process.env.PUBLIC_API_URL || 'http://localhost:8000').origin;
const cspHash = (source) => `sha256-${createHash('sha256').update(source).digest('base64')}`;

// Fully static build: `dist/` is synced as-is to S3 (see .github/workflows/deploy-frontend.yml).
// Record pages read their id from the query string (e.g. /dashboard/link/?code=abc123), so no
// server runtime is needed. The one rewrite, directory indexes (/dashboard/ → /dashboard/index.html,
// which a private bucket doesn't resolve), is a CloudFront Function: infra/cloudfront/static-paths.js.
// https://astro.build/config
export default defineConfig({
  output: 'static',
  // Phase 6.3 — a Content-Security-Policy <meta> on every built page (not in `astro dev`), with
  // the hashes of the scripts Astro emits. scripts/check-csp.mjs checks each build against it.
  security: {
    csp: {
      directives: [
        "default-src 'self'",
        `connect-src 'self' ${API_ORIGIN}`,
        // https: for link previews (Open Graph images) from any site; data: for the small assets
        // the build inlines; blob: for the QR code's PNG export.
        "img-src 'self' https: data: blob:",
        "font-src 'self' data:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        // Trusted Types: the DOM's HTML sinks take TrustedHTML only, made by the one policy in
        // src/utils/html.ts (setHTML, toElement). Browsers without Trusted Types ignore these.
        "require-trusted-types-for 'script'",
        'trusted-types shurly-html',
      ],
      // The inline scripts (src/inline-scripts.mjs), which Astro doesn't hash itself (is:inline).
      scriptDirective: { hashes: INLINE_SCRIPTS.map(cspHash) },
      // Style attributes are set from data (chart widths, tag colours), and no hash can cover an
      // attribute: 'unsafe-inline' for attributes only, while <style> elements keep their hashes.
      styleDirective: { resources: ["'self'", { resource: "'unsafe-inline'", kind: 'attribute' }] },
    },
  },
  site: process.env.PUBLIC_SITE_URL || 'http://localhost:4232',
  devToolbar: { enabled: false },
  // Phase 3.13: accounts are created by signing in with Google, so the sign-up page went.
  // Old bookmarks and emails land on the login page instead of a 404.
  redirects: { '/register': '/login/' },
  // The manual (src/content/manual/): plain code blocks, styled by the design system.
  markdown: { syntaxHighlight: false },
  vite: {
    plugins: [tailwindcss()],
    define: { __SHURLY_MCP_URL__: JSON.stringify(MCP_URL) },
  },
  server: {
    port: 4232,
    host: true,
  },
});
