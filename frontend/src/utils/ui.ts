// Shared UI behaviours: toasts, copy feedback, dialogs, menus, relative time.
// `installGlobalUI()` wires document-level delegation once per page, so markup
// rendered later (innerHTML) gets the behaviours for free via data-attributes:
//   data-copy="text"            copy to clipboard with button feedback
//   data-dialog-open="id"       open <dialog id="id">
//   data-dialog-close           close the enclosing dialog
//   <time data-relative datetime="…">   live "3h ago" label, absolute date in title

import { escapeHtml } from './html';
import { formatDateTime, formatRelative } from './format';
import { iconSvg } from './icons';

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------

export type ToastKind = 'success' | 'error' | 'info';

export interface ToastOptions {
  description?: string;
  duration?: number;
  action?: { label: string; onClick: () => void };
}

function toastRegion(): HTMLElement {
  let region = document.getElementById('toast-region');
  if (!region) {
    region = document.createElement('div');
    region.id = 'toast-region';
    region.className = 'toast-region';
    region.setAttribute('aria-live', 'polite');
    region.setAttribute('aria-relevant', 'additions');
    document.body.appendChild(region);
  }
  return region;
}

const TOAST_ICON: Record<ToastKind, string> = {
  success: `<span class="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-brand-400 text-white animate-pop">${iconSvg('check', 'size-3.5', 3)}</span>`,
  error: `<span class="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-red-500 text-white">${iconSvg('x', 'size-3.5', 3)}</span>`,
  info: `<span class="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-ink-700 text-white">${iconSvg('info', 'size-3.5', 2.5)}</span>`,
};

export function toast(message: string, kind: ToastKind = 'success', opts: ToastOptions = {}): void {
  const region = toastRegion();
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  el.innerHTML = `${TOAST_ICON[kind]}
    <div class="min-w-0 flex-1">
      <p class="font-semibold">${escapeHtml(message)}</p>
      ${opts.description ? `<p class="mt-0.5 text-ink-300">${escapeHtml(opts.description)}</p>` : ''}
    </div>
    ${opts.action ? `<button type="button" data-toast-action class="rounded-md px-2 py-1 text-sm font-semibold text-brand-300 hover:bg-white/10">${escapeHtml(opts.action.label)}</button>` : ''}
    <button type="button" data-toast-close aria-label="Dismiss" class="-mr-1 rounded-md p-1 text-ink-400 hover:bg-white/10 hover:text-white">${iconSvg('x', 'size-4')}</button>`;
  region.appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => (el.dataset.state = 'open')));

  let timer = window.setTimeout(dismiss, opts.duration ?? (kind === 'error' ? 6000 : 4000));
  function dismiss() {
    window.clearTimeout(timer);
    el.dataset.state = 'closing';
    window.setTimeout(() => el.remove(), 220);
  }
  el.addEventListener('mouseenter', () => window.clearTimeout(timer));
  el.addEventListener('mouseleave', () => (timer = window.setTimeout(dismiss, 2000)));
  el.querySelector('[data-toast-close]')?.addEventListener('click', dismiss);
  el.querySelector('[data-toast-action]')?.addEventListener('click', () => {
    opts.action?.onClick();
    dismiss();
  });
}

// ---------------------------------------------------------------------------
// Clipboard
// ---------------------------------------------------------------------------

export async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for non-secure contexts / older browsers
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    ta.remove();
    return ok;
  }
}

/**
 * Copy with in-place feedback: the button turns brand blue, its icon becomes a check and
 * its label (if it has one in [data-copy-label]) reads "Copied!" for 2s.
 */
export async function copyWithFeedback(text: string, button?: HTMLElement | null, toastMessage?: string): Promise<boolean> {
  const ok = await writeClipboard(text);
  if (!ok) {
    toast("Couldn't copy automatically", 'error', { description: 'Select the link and copy it manually.' });
    return false;
  }
  if (button) {
    const iconHost = button.querySelector('[data-copy-icon]');
    const label = button.querySelector('[data-copy-label]');
    const prevIcon = iconHost?.innerHTML;
    const prevLabel = label?.textContent;
    button.dataset.copied = '';
    if (iconHost) iconHost.innerHTML = iconSvg('check', 'size-4 animate-pop', 2.5);
    if (label) label.textContent = 'Copied!';
    window.clearTimeout(Number(button.dataset.copyTimer));
    button.dataset.copyTimer = String(
      window.setTimeout(() => {
        delete button.dataset.copied;
        if (iconHost && prevIcon !== undefined) iconHost.innerHTML = prevIcon;
        if (label && prevLabel !== undefined && prevLabel !== null) label.textContent = prevLabel;
      }, 2000),
    );
  }
  if (toastMessage) toast(toastMessage, 'success');
  return true;
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

/** Swap a button into a loading state (keeps its width stable) and back. */
export function setLoading(button: HTMLButtonElement | null, loading: boolean, label?: string): void {
  if (!button) return;
  if (loading) {
    if (button.dataset.loading !== undefined) return;
    button.dataset.loading = '';
    button.dataset.originalHtml = button.innerHTML;
    button.style.minWidth = `${button.offsetWidth}px`;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.innerHTML = `<span class="spinner"></span><span>${escapeHtml(label ?? button.textContent?.trim() ?? '')}</span>`;
  } else {
    if (button.dataset.loading === undefined) return;
    delete button.dataset.loading;
    button.innerHTML = button.dataset.originalHtml ?? button.innerHTML;
    button.style.minWidth = '';
    button.disabled = false;
    button.removeAttribute('aria-busy');
  }
}

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------

export function openDialog(dialog: HTMLDialogElement | null): void {
  if (!dialog || dialog.open) return;
  dialog.showModal();
  requestAnimationFrame(() => (dialog.dataset.state = 'open'));
  const autofocus = dialog.querySelector<HTMLElement>('[autofocus], [data-autofocus]');
  autofocus?.focus();
}

/** Animates out, then closes. Resolves once closed, i.e. after the browser has restored focus. */
export function closeDialog(dialog: HTMLDialogElement | null, returnValue = ''): Promise<void> {
  if (!dialog || !dialog.open) return Promise.resolve();
  if (dialog.dataset.state === 'closing') {
    return new Promise((resolve) => dialog.addEventListener('close', () => resolve(), { once: true }));
  }
  dialog.dataset.state = 'closing';
  return new Promise((resolve) => {
    window.setTimeout(() => {
      dialog.close(returnValue);
      delete dialog.dataset.state;
      resolve();
    }, 180);
  });
}

export interface ConfirmOptions {
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  /** Async work to run on confirm; the dialog stays open with a loading button until it settles. */
  onConfirm?: () => Promise<void>;
}

/**
 * Promise-based confirmation dialog built on <dialog>. Resolves true when confirmed, once the
 * dialog has fully closed, so callers can move focus straight away.
 */
export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'modal';
    dialog.setAttribute('aria-labelledby', 'confirm-title');
    // Self-managed: the global Escape/backdrop handlers must not close it behind our back.
    dialog.setAttribute('data-managed', '');
    dialog.setAttribute('data-static', '');
    dialog.innerHTML = `
      <div class="modal-panel p-6" style="--modal-width: 28rem">
        <div class="flex gap-4">
          <div class="grid size-10 shrink-0 place-items-center rounded-full ${opts.danger ? 'bg-red-50 text-red-600' : 'bg-ink-100 text-ink-700'}">
            ${iconSvg(opts.danger ? 'warning' : 'help', 'size-5')}
          </div>
          <div class="min-w-0">
            <h2 id="confirm-title" class="text-base font-semibold text-ink-950">${escapeHtml(opts.title)}</h2>
            ${opts.body ? `<p class="mt-1.5 text-sm leading-6 text-ink-600">${escapeHtml(opts.body)}</p>` : ''}
            <p data-confirm-error class="field-error mt-2" hidden></p>
          </div>
        </div>
        <div class="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn btn-secondary" data-cancel>${escapeHtml(opts.cancelLabel ?? 'Cancel')}</button>
          <button type="button" class="btn ${opts.danger ? 'btn-danger' : 'btn-primary'}" data-confirm data-autofocus>${escapeHtml(opts.confirmLabel ?? 'Confirm')}</button>
        </div>
      </div>`;
    document.body.appendChild(dialog);
    const confirmBtn = dialog.querySelector<HTMLButtonElement>('[data-confirm]')!;
    const errorEl = dialog.querySelector<HTMLElement>('[data-confirm-error]')!;
    let settled = false;

    const finish = async (value: boolean) => {
      if (settled) return;
      settled = true;
      await closeDialog(dialog);
      dialog.remove();
      resolve(value);
    };

    const busy = () => confirmBtn.dataset.loading !== undefined;
    dialog.querySelector('[data-cancel]')!.addEventListener('click', () => !busy() && finish(false));
    dialog.addEventListener('cancel', (e) => {
      e.preventDefault();
      if (!busy()) finish(false);
    });
    dialog.addEventListener('click', (e) => {
      if (e.target === dialog && !busy()) finish(false);
    });
    confirmBtn.addEventListener('click', async () => {
      if (!opts.onConfirm) return finish(true);
      errorEl.hidden = true;
      setLoading(confirmBtn, true);
      try {
        await opts.onConfirm();
        finish(true);
      } catch (err) {
        setLoading(confirmBtn, false);
        errorEl.textContent = err instanceof Error ? err.message : 'Something went wrong.';
        errorEl.hidden = false;
      }
    });
    openDialog(dialog);
  });
}

// ---------------------------------------------------------------------------
// Menus (popover API, positioned next to their trigger)
// ---------------------------------------------------------------------------

function positionMenu(menu: HTMLElement, trigger: HTMLElement): void {
  const r = trigger.getBoundingClientRect();
  const align = menu.dataset.align ?? 'end';
  menu.style.position = 'fixed';
  menu.style.margin = '0';
  const mw = menu.offsetWidth;
  const mh = menu.offsetHeight;
  let left = align === 'start' ? r.left : r.right - mw;
  left = Math.max(8, Math.min(left, window.innerWidth - mw - 8));
  let top = r.bottom + 6;
  if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

// ---------------------------------------------------------------------------
// Relative time
// ---------------------------------------------------------------------------

export function hydrateTimes(root: ParentNode = document): void {
  root.querySelectorAll<HTMLTimeElement>('time[data-relative]').forEach((el) => {
    const iso = el.getAttribute('datetime');
    if (!iso) return;
    el.textContent = formatRelative(iso);
    if (!el.title) el.title = formatDateTime(iso);
  });
}

// ---------------------------------------------------------------------------
// Global delegation
// ---------------------------------------------------------------------------

let installed = false;

export function installGlobalUI(): void {
  if (installed) return;
  installed = true;

  document.addEventListener('click', (event) => {
    const target = event.target as HTMLElement;

    const copyBtn = target.closest<HTMLElement>('[data-copy]');
    if (copyBtn) {
      event.preventDefault();
      void copyWithFeedback(copyBtn.dataset.copy ?? '', copyBtn, copyBtn.dataset.copyToast);
      return;
    }

    const opener = target.closest<HTMLElement>('[data-dialog-open]');
    if (opener) {
      openDialog(document.getElementById(opener.dataset.dialogOpen!) as HTMLDialogElement | null);
      return;
    }

    const closer = target.closest<HTMLElement>('[data-dialog-close]');
    if (closer) {
      closeDialog(closer.closest('dialog'));
      return;
    }

    // Light-dismiss: clicking the backdrop (the dialog element itself) closes it.
    if (target instanceof HTMLDialogElement && target.classList.contains('modal') && !target.hasAttribute('data-static')) {
      closeDialog(target);
    }
  });

  // Animate native Escape-close too.
  document.addEventListener(
    'cancel',
    (event) => {
      const dialog = event.target;
      if (dialog instanceof HTMLDialogElement && dialog.classList.contains('modal') && !dialog.hasAttribute('data-managed')) {
        event.preventDefault();
        closeDialog(dialog);
      }
    },
    true,
  );

  // Position popover menus when they open.
  document.addEventListener(
    'toggle',
    (event) => {
      const menu = event.target as HTMLElement;
      if (!(menu instanceof HTMLElement) || !menu.classList.contains('menu')) return;
      if ((event as ToggleEvent).newState !== 'open') return;
      const trigger = document.querySelector<HTMLElement>(`[popovertarget="${menu.id}"]`);
      if (trigger) positionMenu(menu, trigger);
    },
    true,
  );
  window.addEventListener('resize', () => {
    document.querySelectorAll<HTMLElement>('.menu:popover-open').forEach((m) => m.hidePopover());
  });

  // Broken third-party images (OG thumbnails): swap in the sibling <template> fallback
  // if there is one, otherwise a neutral placeholder. `error` doesn't bubble, so capture it.
  document.addEventListener(
    'error',
    (event) => {
      const img = event.target;
      if (!(img instanceof HTMLImageElement) || img.dataset.fallback === undefined) return;
      const wrapper = img.parentElement;
      if (!wrapper) return;
      const tpl = wrapper.nextElementSibling;
      if (tpl instanceof HTMLTemplateElement) wrapper.replaceWith(tpl.content.cloneNode(true));
      else wrapper.innerHTML = `<span class="grid size-full place-items-center text-sm text-ink-400">${iconSvg('image-off', 'size-4')}</span>`;
    },
    true,
  );

  // One-shot toast carried across a navigation (e.g. "Link deleted" after redirecting).
  const flash = sessionStorage.getItem('shurly_flash');
  if (flash) {
    sessionStorage.removeItem('shurly_flash');
    toast(flash, 'success');
  }

  hydrateTimes();
  window.setInterval(() => hydrateTimes(), 60_000);
}
