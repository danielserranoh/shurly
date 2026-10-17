// Phase 3.12.10, 3.14.6 — the photo dialog's rules (src/utils/photo-picker-state.ts), shared by the avatar and
// the organization's logo: what the circle shows on open, after Change and after Remove; Remove only when there's
// something to remove; Save only once something would change, and what it does; Cancel keeps what there was. And
// how the positioned square is exported: the avatar as before, the logo with its transparency.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  exportFor,
  hasChanges,
  OUTPUT_SIDE,
  openPicker,
  pickerView,
  pickNew,
  removePhoto,
  saveAction,
} from '../src/utils/photo-picker-state.ts';

describe('on open', () => {
  test('with a photo: it shows, read-only, with Remove, and nothing to save', () => {
    const state = openPicker(true);
    assert.deepEqual(pickerView(state), { shows: 'current', positioning: false, canRemove: true, canSave: false });
    assert.equal(saveAction(state), null);
    assert.equal(hasChanges(state), false);
  });

  test('without one: the initial, no Remove, nothing to save', () => {
    const state = openPicker(false);
    assert.deepEqual(pickerView(state), { shows: 'initials', positioning: false, canRemove: false, canSave: false });
    assert.equal(saveAction(state), null);
  });
});

describe('Change photo', () => {
  for (const hasCurrent of [true, false]) {
    test(`${hasCurrent ? 'with' : 'without'} a photo: the new one is positioned, Remove shows, Save uploads`, () => {
      const state = pickNew(openPicker(hasCurrent));
      assert.deepEqual(pickerView(state), { shows: 'new', positioning: true, canRemove: true, canSave: true });
      assert.equal(saveAction(state), 'upload');
    });
  }

  test('after Remove: the new one replaces the initial, and Save uploads it', () => {
    const state = pickNew(removePhoto(openPicker(true)));
    assert.equal(pickerView(state).shows, 'new');
    assert.equal(saveAction(state), 'upload');
  });

  test('again: still one new photo to upload', () => {
    assert.equal(saveAction(pickNew(pickNew(openPicker(true)))), 'upload');
  });
});

describe('Remove photo', () => {
  test('the saved photo: the initial shows, Remove hides, Save deletes', () => {
    const state = removePhoto(openPicker(true));
    assert.deepEqual(pickerView(state), { shows: 'initials', positioning: false, canRemove: false, canSave: true });
    assert.equal(saveAction(state), 'delete');
  });

  test('a new photo over a saved one: the initial, and Save deletes the saved one', () => {
    const state = removePhoto(pickNew(openPicker(true)));
    assert.equal(pickerView(state).shows, 'initials');
    assert.equal(saveAction(state), 'delete');
  });

  test('a new photo with none saved: back to how it opened, nothing to save', () => {
    const state = removePhoto(pickNew(openPicker(false)));
    assert.deepEqual(state, openPicker(false));
    assert.deepEqual(pickerView(state), { shows: 'initials', positioning: false, canRemove: false, canSave: false });
    assert.equal(saveAction(state), null);
  });
});

describe('Save is enabled only once something would change', () => {
  const paths = {
    'open, with a photo': [true, []],
    'open, without one': [false, []],
    'change': [true, [pickNew]],
    'remove': [true, [removePhoto]],
    'change, then remove, without one saved': [false, [pickNew, removePhoto]],
    'remove, then change': [true, [removePhoto, pickNew]],
  };
  const expected = {
    'open, with a photo': false,
    'open, without one': false,
    'change': true,
    'remove': true,
    'change, then remove, without one saved': false,
    'remove, then change': true,
  };
  for (const [name, [hasCurrent, steps]] of Object.entries(paths)) {
    test(name, () => {
      const state = steps.reduce((s, step) => step(s), openPicker(hasCurrent));
      assert.equal(pickerView(state).canSave, expected[name]);
      assert.equal(hasChanges(state), expected[name]);
      assert.equal(saveAction(state) !== null, expected[name]);
    });
  }
});

describe('Cancel', () => {
  test('keeps what there was: opening again starts from the saved photo, whatever was pending', () => {
    for (const hasCurrent of [true, false]) {
      for (const pending of [pickNew, removePhoto]) {
        pending(openPicker(hasCurrent)); // dropped by Cancel: nothing was sent
        assert.deepEqual(pickerView(openPicker(hasCurrent)).shows, hasCurrent ? 'current' : 'initials');
        assert.equal(saveAction(openPicker(hasCurrent)), null);
      }
    }
  });

  test('never changes the state it was given', () => {
    const state = Object.freeze(openPicker(true));
    pickNew(state);
    removePhoto(state);
    assert.deepEqual(state, { hasCurrent: true, pending: null });
  });
});

describe('the export', () => {
  test('the avatar: a 512 px WebP, as before, whatever the source', () => {
    for (const source of [80, 512, 3000]) assert.deepEqual(exportFor('avatar', source), { type: 'image/webp', quality: 0.9, side: OUTPUT_SIDE });
  });

  test('the logo: a PNG, lossless with its alpha, never a JPEG', () => {
    const out = exportFor('logo', 800);
    assert.equal(out.type, 'image/png');
    assert.equal(out.quality, undefined);
    assert.notEqual(out.type, 'image/jpeg');
  });

  test('the logo: at most 512 px, never enlarged', () => {
    assert.equal(exportFor('logo', 3000).side, 512);
    assert.equal(exportFor('logo', 512).side, 512);
    assert.equal(exportFor('logo', 80).side, 80);
    assert.equal(exportFor('logo', 79.6).side, 80);
    assert.equal(exportFor('logo', 0.2).side, 1);
  });
});
