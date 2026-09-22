// Tag picker: an accessible combobox with starts-with matching and inline creation.
// Markup comes from components/ui/TagInput.astro (or is created by `mountTagInput`).

import { errorMessage } from './api';
import { escapeHtml } from './html';
import { iconSvg } from './icons';
import { CATEGORY_LABELS, createTag, loadTags, tagColorAttrs, tagPill } from './tags';
import { toast } from './ui';
import type { Tag } from './types';

export interface TagInputHandle {
  getIds(): string[];
  setTags(tags: Tag[]): void;
  clear(): void;
  onChange(cb: (tags: Tag[]) => void): void;
}

let uid = 0;

export function mountTagInput(root: HTMLElement): TagInputHandle {
  const id = `taginput-${++uid}`;
  root.classList.add('relative');
  root.innerHTML = `
    <div class="flex min-h-10 flex-wrap items-center gap-1.5 rounded-[var(--radius-lg)] border border-ink-200 bg-white px-2 py-1.5 shadow-xs transition-[border-color,box-shadow] hover:border-ink-300 focus-within:border-ink-950 focus-within:shadow-[0_0_0_1px_var(--color-ink-950),0_0_0_5px_var(--color-brand-200)]" data-box>
      <span class="contents" data-selected></span>
      <input type="text" class="h-7 min-w-32 flex-1 bg-transparent px-1 text-sm text-ink-900 outline-none placeholder:text-ink-500"
        role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${id}-list" autocomplete="off"
        placeholder="${escapeHtml(root.dataset.placeholder ?? 'Add tags…')}" aria-label="${escapeHtml(root.dataset.label ?? 'Tags')}" />
    </div>
    <ul id="${id}-list" role="listbox" hidden class="absolute inset-x-0 top-full z-30 mt-1.5 max-h-64 overflow-y-auto rounded-xl border border-line bg-white p-1.5 shadow-lg"></ul>`;

  const box = root.querySelector<HTMLElement>('[data-box]')!;
  const selectedEl = root.querySelector<HTMLElement>('[data-selected]')!;
  const input = root.querySelector<HTMLInputElement>('input')!;
  const list = root.querySelector<HTMLUListElement>('ul')!;

  let all: Tag[] = [];
  let selected: Tag[] = [];
  let options: ({ kind: 'tag'; tag: Tag } | { kind: 'create'; name: string })[] = [];
  let active = -1;
  const listeners: ((tags: Tag[]) => void)[] = [];

  loadTags()
    .then((tags) => (all = tags))
    .catch(() => (all = []));

  const emit = () => listeners.forEach((cb) => cb([...selected]));

  function renderSelected() {
    selectedEl.innerHTML = selected.map((t) => tagPill(t, { removable: true }).value).join('');
  }

  function close() {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }

  function renderOptions() {
    const q = input.value.trim().toLowerCase();
    const chosen = new Set(selected.map((t) => t.id));
    const pool = all.filter((t) => !chosen.has(t.id));
    const matches = (q ? pool.filter((t) => t.name.startsWith(q) || t.display_name.toLowerCase().startsWith(q)) : pool)
      .sort((a, b) => Number(b.is_predefined) - Number(a.is_predefined) || b.usage_count - a.usage_count || a.name.localeCompare(b.name))
      .slice(0, 30);
    options = matches.map((tag) => ({ kind: 'tag' as const, tag }));
    const exact = all.some((t) => t.name === q);
    if (q && !exact && q.length <= 30) options.push({ kind: 'create', name: input.value.trim() });
    if (active >= options.length) active = options.length - 1;

    if (!options.length) {
      list.innerHTML = `<li class="px-3 py-2 text-sm text-ink-500">${q ? 'No matching tags' : 'No more tags — type to create one'}</li>`;
    } else {
      list.innerHTML = options
        .map((opt, i) => {
          const common = `id="${id}-opt-${i}" role="option" data-index="${i}" aria-selected="${i === active}" class="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm ${i === active ? 'bg-ink-100' : ''} hover:bg-ink-100"`;
          if (opt.kind === 'create') {
            return `<li ${common}><span class="grid size-5 place-items-center rounded-md bg-ink-950 text-brand-300">${iconSvg('plus', 'size-3.5', 2.5)}</span><span>Create <b class="font-semibold">“${escapeHtml(opt.name)}”</b></span></li>`;
          }
          const { family } = tagColorAttrs(opt.tag.color);
          const category = opt.tag.is_predefined && family ? CATEGORY_LABELS[family] : 'Your tag';
          return `<li ${common}>${tagPill(opt.tag).value}<span class="ml-auto text-xs text-ink-500">${escapeHtml(category ?? '')}</span></li>`;
        })
        .join('');
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    if (active >= 0) input.setAttribute('aria-activedescendant', `${id}-opt-${active}`);
  }

  async function choose(index: number) {
    const opt = options[index];
    if (!opt) return;
    if (opt.kind === 'tag') {
      selected.push(opt.tag);
    } else {
      try {
        const tag = await createTag(opt.name);
        all = [...all, tag];
        selected.push(tag);
        toast(`Tag “${tag.display_name}” created`, 'success');
      } catch (err) {
        toast('Couldn’t create that tag', 'error', { description: errorMessage(err) });
        return;
      }
    }
    input.value = '';
    renderSelected();
    // Close after each pick so the list never sits over the buttons below it; typing,
    // ArrowDown or a click reopens it.
    close();
    emit();
    input.focus();
  }

  function remove(tagId: string) {
    selected = selected.filter((t) => t.id !== tagId);
    renderSelected();
    emit();
    if (!list.hidden) renderOptions();
  }

  // Open on click rather than focus, so a dialog that focuses this field doesn't
  // immediately cover its own footer.
  function open() {
    if (!list.hidden) return;
    active = -1;
    renderOptions();
  }
  input.addEventListener('click', open);
  input.addEventListener('input', () => {
    active = input.value.trim() ? 0 : -1;
    renderOptions();
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (list.hidden) renderOptions();
      active = Math.min(active + 1, options.length - 1);
      renderOptions();
      list.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      active = Math.max(active - 1, 0);
      renderOptions();
      list.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      if (!list.hidden && active >= 0) {
        e.preventDefault();
        void choose(active);
      } else if (input.value.trim()) {
        e.preventDefault();
      }
    } else if (e.key === 'Escape') {
      if (!list.hidden) {
        e.preventDefault();
        e.stopPropagation();
        close();
      }
    } else if (e.key === 'Backspace' && !input.value && selected.length) {
      remove(selected[selected.length - 1].id);
    }
  });
  list.addEventListener('mousedown', (e) => e.preventDefault()); // keep focus in the input
  list.addEventListener('click', (e) => {
    const li = (e.target as HTMLElement).closest<HTMLElement>('[data-index]');
    if (li) void choose(Number(li.dataset.index));
  });
  selectedEl.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLElement>('[data-remove-tag]');
    if (btn) remove(btn.dataset.removeTag!);
  });
  selectedEl.addEventListener('keydown', (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLElement>('[data-remove-tag]');
    if (btn && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      remove(btn.dataset.removeTag!);
      input.focus();
    }
  });
  box.addEventListener('click', (e) => {
    if (e.target !== box) return;
    input.focus();
    open();
  });
  document.addEventListener('pointerdown', (e) => {
    if (!root.contains(e.target as Node)) close();
  });
  root.addEventListener('focusout', (e) => {
    if (!root.contains(e.relatedTarget as Node)) close();
  });

  return {
    getIds: () => selected.map((t) => t.id),
    setTags(tags: Tag[]) {
      selected = [...tags];
      renderSelected();
    },
    clear() {
      selected = [];
      input.value = '';
      renderSelected();
    },
    onChange(cb) {
      listeners.push(cb);
    },
  };
}
