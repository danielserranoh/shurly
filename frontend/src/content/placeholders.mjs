// Phase 5.9 — build-time values in the manual: `{{MCP_URL}}` in the Markdown becomes this
// build's MCP endpoint when the page is built (components/manual/ManualArticle.astro). An
// unknown placeholder fails the build instead of reaching a reader.

const PLACEHOLDER = /\{\{(\w+)\}\}/g;

/**
 * @param {string} text
 * @param {Record<string, string>} values already escaped for where they land
 * @returns {string}
 */
export function fillPlaceholders(text, values) {
  return text.replace(PLACEHOLDER, (match, name) => {
    if (!Object.hasOwn(values, name)) throw new Error(`Unknown placeholder ${match} in the manual`);
    return values[name];
  });
}

/**
 * The MCP endpoint the manual and Settings show: PUBLIC_MCP_URL, or the API's /mcp/. Always
 * with the trailing slash, the address people must use (5.8: OAuth ties the client to it).
 * @param {Record<string, string | undefined>} env
 * @returns {string}
 */
export function mcpUrl(env) {
  const api = (env.PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
  return (env.PUBLIC_MCP_URL || `${api}/mcp`).replace(/\/*$/, '/');
}
