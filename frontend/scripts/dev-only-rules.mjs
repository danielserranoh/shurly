// Phase 3.16/3.17 — development-only code never reaches a production build. The analytics mocks
// (src/utils/link-analytics-mock.ts and campaign-analytics-mock.ts, loaded by `&mock` under
// `import.meta.env.DEV` only) carry DEV_ONLY_MARKER in a string they use, so it shows in any script that
// bundles them, minified or not.

export const DEV_ONLY_MARKER = 'shurly-dev-only';
/** Chunk names that give a development-only module away. */
const DEV_ONLY_CHUNKS = ['link-analytics-mock', 'campaign-analytics-mock'];

/** Problems with the built scripts (`{name, source}`): one per script that carries development-only code. */
export function checkDevOnly(files) {
  const problems = [];
  for (const { name, source } of files) {
    const chunk = DEV_ONLY_CHUNKS.find((dev) => name.includes(dev));
    const found = chunk ?? (source.includes(DEV_ONLY_MARKER) ? DEV_ONLY_MARKER : null);
    if (found) problems.push(`${name}: development-only code (${found}) in a production build`);
  }
  return problems;
}
