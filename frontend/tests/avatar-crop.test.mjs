// Phase 3.12 — the avatar crop's hard rule: the frame (and so the circle) is always fully
// covered by the image, at every zoom and after every move.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  clampCrop,
  initialCrop,
  MAX_ZOOM_FACTOR,
  maxZoom,
  minZoom,
  panBy,
  sliderFor,
  sourceSquare,
  zoomFor,
  zoomTo,
} from '../src/utils/avatar-crop.ts';

const SIZE = 256;
const EPSILON = 1e-9;
const IMAGES = {
  portrait: { width: 600, height: 900, size: SIZE },
  landscape: { width: 1600, height: 900, size: SIZE },
  square: { width: 800, height: 800, size: SIZE },
  small: { width: 40, height: 30, size: SIZE },
};

/** The frame is covered: no image edge inside it. */
function assertCovers(crop, frame) {
  assert.ok(crop.x <= EPSILON && crop.y <= EPSILON, `top-left inside the frame: ${JSON.stringify(crop)}`);
  assert.ok(crop.x + frame.width * crop.zoom >= frame.size - EPSILON, `right edge inside: ${JSON.stringify(crop)}`);
  assert.ok(crop.y + frame.height * crop.zoom >= frame.size - EPSILON, `bottom edge inside: ${JSON.stringify(crop)}`);
}

for (const [name, frame] of Object.entries(IMAGES)) {
  describe(`a ${name} image`, () => {
    test('opens at the smallest zoom, its shorter side filling the frame, centred', () => {
      const crop = initialCrop(frame);
      assert.equal(crop.zoom, minZoom(frame));
      assert.ok(Math.abs(Math.min(frame.width, frame.height) * crop.zoom - SIZE) < EPSILON);
      assertCovers(crop, frame);
      // Centred: as much image left and right (and above and below) of the frame.
      assert.ok(Math.abs(-crop.x - (crop.x + frame.width * crop.zoom - SIZE)) < 1e-6);
      assert.ok(Math.abs(-crop.y - (crop.y + frame.height * crop.zoom - SIZE)) < 1e-6);
    });

    test("can't zoom out past covering, or in past the limit", () => {
      const crop = initialCrop(frame);
      assert.equal(zoomTo(crop, minZoom(frame) / 3, frame).zoom, minZoom(frame));
      assert.equal(zoomTo(crop, minZoom(frame) * 100, frame).zoom, maxZoom(frame));
    });

    test('stays covered when dragged far in any direction, at every zoom', () => {
      for (const factor of [1, 1.5, 2, 3, MAX_ZOOM_FACTOR]) {
        const zoomed = zoomTo(initialCrop(frame), minZoom(frame) * factor, frame);
        for (const [dx, dy] of [[5000, 0], [-5000, 0], [0, 5000], [0, -5000], [5000, 5000], [-5000, -5000], [12, -7]]) {
          assertCovers(panBy(zoomed, dx, dy, frame), frame);
        }
      }
    });

    test('stays covered when zooming out from a corner (re-clamped)', () => {
      const deep = zoomTo(initialCrop(frame), maxZoom(frame), frame);
      const cornered = panBy(deep, -1e6, -1e6, frame);
      for (const factor of [3, 2, 1.2, 1]) {
        assertCovers(zoomTo(cornered, minZoom(frame) * factor, frame), frame);
      }
    });

    test('the saved square lies inside the image', () => {
      const deep = panBy(zoomTo(initialCrop(frame), maxZoom(frame) * 0.7, frame), 33, -41, frame);
      for (const crop of [initialCrop(frame), deep]) {
        const square = sourceSquare(crop, frame);
        assert.ok(square.x >= -EPSILON && square.y >= -EPSILON);
        assert.ok(square.x + square.size <= frame.width + 1e-6);
        assert.ok(square.y + square.size <= frame.height + 1e-6);
      }
    });
  });
}

describe('zoomTo', () => {
  test('keeps the point under the cursor where it is', () => {
    const frame = IMAGES.landscape;
    const crop = zoomTo(initialCrop(frame), minZoom(frame) * 2, frame);
    const [atX, atY] = [100, 140];
    const before = [(atX - crop.x) / crop.zoom, (atY - crop.y) / crop.zoom];

    const zoomed = zoomTo(crop, crop.zoom * 1.3, frame, atX, atY);

    const after = [(atX - zoomed.x) / zoomed.zoom, (atY - zoomed.y) / zoomed.zoom];
    assert.ok(Math.abs(before[0] - after[0]) < 1e-6 && Math.abs(before[1] - after[1]) < 1e-6);
  });
});

describe('clampCrop', () => {
  test('pulls a crop with a gap back to the edge', () => {
    const frame = IMAGES.square;
    const clamped = clampCrop({ zoom: minZoom(frame), x: 30, y: -1e6 }, frame);
    assert.equal(clamped.x, 0);
    assertCovers(clamped, frame);
  });
});

describe('the zoom slider', () => {
  test('0 is the smallest zoom and 1 the largest, and back again', () => {
    const frame = IMAGES.portrait;
    assert.equal(zoomFor(0, frame), minZoom(frame));
    assert.ok(Math.abs(zoomFor(1, frame) - maxZoom(frame)) < EPSILON);
    for (const position of [0, 0.25, 0.5, 0.9, 1]) {
      assert.ok(Math.abs(sliderFor(zoomFor(position, frame), frame) - position) < EPSILON);
    }
  });

  test('stays within its range', () => {
    const frame = IMAGES.portrait;
    assert.equal(zoomFor(-1, frame), minZoom(frame));
    assert.ok(Math.abs(zoomFor(2, frame) - maxZoom(frame)) < EPSILON);
  });
});
