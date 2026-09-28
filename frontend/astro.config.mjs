import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

// Fully static build: `dist/` is synced as-is to S3 (see .github/workflows/deploy-frontend.yml).
// Record pages read their id from the query string (e.g. /dashboard/link/?code=abc123),
// so no server runtime or CDN rewrite rules are needed.
// https://astro.build/config
export default defineConfig({
  output: 'static',
  site: process.env.PUBLIC_SITE_URL || 'http://localhost:4232',
  devToolbar: { enabled: false },
  // Phase 3.13: accounts are created by signing in with Google, so the sign-up page went.
  // Old bookmarks and emails land on the login page instead of a 404.
  redirects: { '/register': '/login/' },
  vite: {
    plugins: [tailwindcss()],
  },
  server: {
    port: 4232,
    host: true,
  },
});
