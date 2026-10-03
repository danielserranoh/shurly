// Phase 8.7 — a link's social preview (src/utils/preview.ts): each field the override a person typed, else the
// destination page's own; and what its thumbnail tries in turn: the image (with the page's icon as a badge), the
// icon on a tile, the monogram.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { linkPreview, thumbSteps } from '../src/utils/preview.ts';

const PAGE = {
  page_og_title: 'The page’s title',
  page_og_description: 'The page’s description',
  page_og_image_url: 'https://example.com/share.png',
  page_favicon_url: 'https://example.com/favicon.svg',
};
const NONE = { og_title: null, og_description: null, og_image_url: null };

describe('linkPreview', () => {
  test('nothing rewritten: the page’s own', () => {
    const preview = linkPreview({ ...NONE, ...PAGE });
    assert.equal(preview.title, 'The page’s title');
    assert.equal(preview.image, 'https://example.com/share.png');
    assert.equal(preview.favicon, 'https://example.com/favicon.svg');
    assert.deepEqual(preview.overridden, { title: false, description: false, image: false });
    assert.equal(preview.custom, false);
  });

  test('each field the override, else the page’s', () => {
    const preview = linkPreview({ ...NONE, ...PAGE, og_title: 'Mine' });
    assert.equal(preview.title, 'Mine');
    assert.equal(preview.description, 'The page’s description');
    assert.deepEqual(preview.overridden, { title: true, description: false, image: false });
    assert.equal(preview.custom, true);
  });

  test('an API from before 8.7, without the page’s fields', () => {
    const preview = linkPreview({ og_title: 'Old', og_description: null, og_image_url: 'https://e.com/i.png' });
    assert.equal(preview.title, 'Old');
    assert.equal(preview.favicon, null);
  });

  test('a blank override is none', () => {
    assert.equal(linkPreview({ ...NONE, ...PAGE, og_title: '  ' }).overridden.title, false);
  });
});

describe('thumbSteps', () => {
  test('an image, with the icon as a badge, then the icon, then the monogram', () => {
    assert.deepEqual(thumbSteps({ ...NONE, ...PAGE }), [
      { kind: 'image', src: 'https://example.com/share.png', badge: 'https://example.com/favicon.svg' },
      { kind: 'favicon', src: 'https://example.com/favicon.svg' },
      { kind: 'monogram' },
    ]);
  });

  test('the image a person set comes first', () => {
    const [first] = thumbSteps({ ...NONE, ...PAGE, og_image_url: 'https://e.com/mine.png' });
    assert.equal(first.src, 'https://e.com/mine.png');
  });

  test('no image: the icon on a tile', () => {
    assert.deepEqual(thumbSteps({ ...NONE, page_favicon_url: 'https://e.com/favicon.ico' }), [
      { kind: 'favicon', src: 'https://e.com/favicon.ico' },
      { kind: 'monogram' },
    ]);
  });

  test('an image without an icon: no badge', () => {
    assert.deepEqual(thumbSteps({ ...NONE, page_og_image_url: 'https://e.com/i.png' }), [
      { kind: 'image', src: 'https://e.com/i.png', badge: null },
      { kind: 'monogram' },
    ]);
  });

  test('neither: the monogram', () => {
    assert.deepEqual(thumbSteps(NONE), [{ kind: 'monogram' }]);
  });
});
