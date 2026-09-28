// Phase 5.9 — the user manual: Markdown in src/content/manual/, rendered at build time.
// Published under /manual/, and Settings → API & MCP shows the MCP page from the same file.

import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const manual = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/manual' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    /** Position in the manual's index. */
    order: z.number(),
  }),
});

export const collections = { manual };
