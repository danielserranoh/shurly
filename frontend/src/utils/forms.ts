// Inline validation helpers. Field errors render in `[data-error-for="<name>"]`
// elements and flip aria-invalid on the matching control, so screen readers get them too.

import { ApiError } from './api';
import { escapeHtml } from './html';
import { iconSvg } from './icons';

export function fieldControl(form: HTMLElement, name: string): HTMLElement | null {
  return form.querySelector<HTMLElement>(`[name="${name}"]`);
}

export function setFieldError(form: HTMLElement, name: string, message: string | null): void {
  const control = fieldControl(form, name);
  const slot = form.querySelector<HTMLElement>(`[data-error-for="${name}"]`);
  if (control) {
    if (message) control.setAttribute('aria-invalid', 'true');
    else control.removeAttribute('aria-invalid');
    control.closest('.input-group')?.toggleAttribute('data-invalid', Boolean(message));
  }
  if (slot) {
    slot.textContent = message ?? '';
    slot.hidden = !message;
  }
}

export function clearErrors(form: HTMLElement): void {
  form.querySelectorAll<HTMLElement>('[data-error-for]').forEach((slot) => {
    slot.hidden = true;
    slot.textContent = '';
  });
  form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
  form.querySelectorAll('.input-group[data-invalid]').forEach((el) => el.removeAttribute('data-invalid'));
  showAlert(form, null);
}

/** Form-level message in `[data-form-alert]`. */
export function showAlert(form: HTMLElement, message: string | null, kind: 'error' | 'info' | 'success' = 'error'): void {
  const box = form.querySelector<HTMLElement>('[data-form-alert]');
  if (!box) return;
  if (!message) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  const styles = {
    error: ['border-red-200 bg-red-50 text-red-800', 'circle-alert', 'text-red-600'],
    info: ['border-ink-200 bg-ink-50 text-ink-800', 'info', 'text-ink-500'],
    success: ['border-brand-200 bg-brand-50 text-brand-900', 'circle-check', 'text-brand-700'],
  } as const;
  const [cls, ic, icCls] = styles[kind];
  box.className = `flex gap-2.5 rounded-xl border px-3.5 py-3 text-sm ${cls}`;
  box.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  box.innerHTML = `<span class="mt-0.5 shrink-0 ${icCls}">${iconSvg(ic, 'size-4')}</span><p>${escapeHtml(message)}</p>`;
  box.hidden = false;
}

/** Map an API error onto fields (422) or the form alert. Returns true if any field matched. */
export function applyApiError(form: HTMLElement, error: unknown, fieldMap: Record<string, string> = {}): boolean {
  if (error instanceof ApiError && Object.keys(error.fields).length) {
    let matched = false;
    for (const [apiField, message] of Object.entries(error.fields)) {
      const name = fieldMap[apiField] ?? apiField;
      if (form.querySelector(`[data-error-for="${name}"]`)) {
        setFieldError(form, name, message);
        matched = true;
      }
    }
    if (matched) {
      revealFirstError(form);
      return true;
    }
  }
  showAlert(form, error instanceof Error ? error.message : 'Something went wrong. Please try again.');
  return false;
}

/** Focus the first invalid control, expanding any collapsed <details> that hides it. */
export function revealFirstError(form: HTMLElement): void {
  const el = form.querySelector<HTMLElement>('[aria-invalid="true"]');
  if (!el) return;
  for (let d = el.closest('details'); d; d = d.parentElement?.closest('details') ?? null) d.open = true;
  el.focus();
}

export function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value.trim());
}
