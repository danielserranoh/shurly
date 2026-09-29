// Phase 3.12, 3.14.4 — what a picked or dropped image is checked for before it's sent
// (src/utils/image-file.ts): the avatar takes up to 10 MB (it's cropped in the browser first), the
// organization's logo the API's own 2 MB (it's sent as it is). Never an SVG. And who may change the
// logo: owners and admins.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  ACCEPTED_TYPES,
  AVATAR_MAX_BYTES,
  avatarFileProblem,
  canChangeLogo,
  imageFileProblem,
  LOGO_MAX_BYTES,
  logoFileProblem,
} from '../src/utils/image-file.ts';

const MB = 1024 * 1024;
const file = (type, size = 1000) => ({ type, size });

describe('imageFileProblem', () => {
  test('takes a JPEG, PNG or WebP within the limit', () => {
    for (const type of ACCEPTED_TYPES) assert.equal(imageFileProblem(file(type), MB), null);
  });

  test('refuses anything else, an SVG and a GIF included', () => {
    for (const type of ['image/svg+xml', 'image/gif', 'application/pdf', '']) {
      assert.equal(imageFileProblem(file(type), MB), 'Use a JPEG, PNG or WebP image.');
    }
  });

  test('refuses a file over the limit, and says the limit', () => {
    assert.equal(imageFileProblem(file('image/png', 2 * MB), 2 * MB), null);
    assert.equal(imageFileProblem(file('image/png', 2 * MB + 1), 2 * MB), 'That image is over 2 MB. Try a smaller one.');
  });
});

describe('the avatar and the logo', () => {
  test('an avatar can be 10 MB, since the crop makes it small', () => {
    assert.equal(AVATAR_MAX_BYTES, 10 * MB);
    assert.equal(avatarFileProblem(file('image/jpeg', 5 * MB)), null);
    assert.match(avatarFileProblem(file('image/jpeg', 11 * MB)), /over 10 MB/);
  });

  test('a logo can be 2 MB, the API’s limit, since it’s sent as it is', () => {
    assert.equal(LOGO_MAX_BYTES, 2 * MB);
    assert.equal(logoFileProblem(file('image/png', 2 * MB)), null);
    assert.match(logoFileProblem(file('image/png', 3 * MB)), /over 2 MB/);
    assert.equal(logoFileProblem(file('image/svg+xml')), 'Use a JPEG, PNG or WebP image.');
  });
});

describe('canChangeLogo', () => {
  test('owners and admins', () => {
    assert.equal(canChangeLogo('owner'), true);
    assert.equal(canChangeLogo('admin'), true);
  });

  test('not members, nor someone outside the organization', () => {
    assert.equal(canChangeLogo('member'), false);
    assert.equal(canChangeLogo(null), false);
    assert.equal(canChangeLogo(undefined), false);
  });
});
