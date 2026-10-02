// Phase 5.9 — the user manual: its build-time values, and the in-app command that must say
// what the manual says.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import { fillPlaceholders, mcpUrl } from '../src/content/placeholders.mjs';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

describe('mcpUrl', () => {
  test('defaults to the API’s /mcp/, with the trailing slash', () => {
    assert.equal(mcpUrl({}), 'http://localhost:8000/mcp/');
    assert.equal(mcpUrl({ PUBLIC_API_URL: 'https://shurly.griddo.io/' }), 'https://shurly.griddo.io/mcp/');
  });

  test('takes PUBLIC_MCP_URL, and always ends it with one slash', () => {
    assert.equal(mcpUrl({ PUBLIC_MCP_URL: 'https://go.griddo.io/mcp' }), 'https://go.griddo.io/mcp/');
    assert.equal(mcpUrl({ PUBLIC_MCP_URL: 'https://go.griddo.io/mcp//', PUBLIC_API_URL: 'https://x' }), 'https://go.griddo.io/mcp/');
  });
});

describe('fillPlaceholders', () => {
  test('fills every occurrence', () => {
    const html = '<pre><code>claude mcp add shurly {{MCP_URL}}</code></pre><p>{{MCP_URL}}</p>';
    assert.equal(fillPlaceholders(html, { MCP_URL: 'https://shurly.griddo.io/mcp/' }), '<pre><code>claude mcp add shurly https://shurly.griddo.io/mcp/</code></pre><p>https://shurly.griddo.io/mcp/</p>');
  });

  test('an unknown placeholder fails the build', () => {
    assert.throws(() => fillPlaceholders('{{MCP_ULR}}', { MCP_URL: 'x' }), /Unknown placeholder \{\{MCP_ULR\}\}/);
  });

  test('the manual only uses placeholders the build fills', () => {
    const manual = read('src/content/manual/install-mcp.md');
    assert.doesNotThrow(() => fillPlaceholders(manual, { MCP_URL: 'x' }));
  });
});

test('“Copy with my key” copies the manual’s own command', () => {
  const manual = read('src/content/manual/install-mcp.md');
  const panel = read('src/components/settings/ApiPanel.astro');
  const inManual = manual.split('\n').find((line) => line.includes('--header'))?.trim();
  const inApp = panel.match(/const mcpKeyCommand = \(k: string\) => `([^`]+)`/)?.[1];
  assert.ok(inManual && inApp, 'both commands found');
  assert.equal(inApp.replace('${site.mcpUrl}', '{{MCP_URL}}').replace('${k}', '<your API key>'), inManual);
});
