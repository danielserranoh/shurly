import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import { mcpUrl } from './src/content/placeholders.mjs';

// Phase 5.9 — one value for the manual's Markdown and for the app's scripts.
const MCP_URL = mcpUrl(process.env);

// Fully static build: `dist/` is synced as-is to S3 (see .github/workflows/deploy-frontend.yml).
// Record pages read their id from the query string (e.g. /dashboard/link/?code=abc123), so no
// server runtime is needed. The one rewrite, directory indexes (/dashboard/ → /dashboard/index.html,
// which a private bucket doesn't resolve), is a CloudFront Function: infra/cloudfront/static-paths.js.
// https://astro.build/config
export default defineConfig({
  output: 'static',
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
