// A link's back-half, as the API takes a custom one (server/utils/url.py, MAX_SHORT_CODE_LENGTH):
// 3 to 64 letters, numbers, hyphens or underscores. 64 since Phase 8.4: Shlink's imported codes
// run to 44 characters. No imports, so tests/short-code.test.mjs can run it as is.

export const MAX_CODE_LENGTH = 64;

const CUSTOM_CODE = new RegExp(`^[A-Za-z0-9_-]{3,${MAX_CODE_LENGTH}}$`);

/** A back-half the API takes as a custom code. */
export function isValidCustomCode(code: string): boolean {
  return CUSTOM_CODE.test(code);
}
