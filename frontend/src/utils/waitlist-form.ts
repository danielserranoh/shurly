// Phase 9.1 — the waitlist's form (pages/waitlist.astro): what it checks before sending, and what it sends to
// POST /api/v1/waitlist. The API checks it all again (server/schemas/waitlist.py), with the same limits.
// No imports: `npm test` runs this file under node --test.

export type WaitlistKind = 'individual' | 'company';

export const COMPANY_SIZES = [
  { value: '1-10', label: '1–10 people' },
  { value: '11-50', label: '11–50 people' },
  { value: '51-200', label: '51–200 people' },
  { value: '201-1000', label: '201–1,000 people' },
  { value: '1000+', label: 'More than 1,000' },
] as const;

export const SOURCES = ['Search engine', 'LinkedIn', 'A colleague or friend', 'Griddo', 'An event', 'Other'] as const;

/** The columns' lengths (server/core/models/waitlist.py). */
export const LIMITS = { email: 254, name: 200, company: 200, role: 120, use_case: 1000, source: 100 } as const;

/** What the form holds, as typed. */
export interface WaitlistValues {
  email: string;
  name: string;
  kind: string;
  company: string;
  company_size: string;
  role: string;
  use_case: string;
  source: string;
  consent: boolean;
  /** The honeypot: hidden from people, so only a bot fills it. */
  website: string;
}

export interface WaitlistBody {
  email: string;
  name: string;
  kind: WaitlistKind;
  company: string | null;
  company_size: string | null;
  role: string | null;
  use_case: string | null;
  source: string | null;
  consent: true;
  website: string | null;
}

// As forms.ts's isEmail.
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

const tooLong = (limit: number) => `Keep it under ${limit.toLocaleString('en-US')} characters.`;

/** Each field's problem, by its name: none when the form can be sent. */
export function waitlistErrors(values: WaitlistValues): Record<string, string> {
  const errors: Record<string, string> = {};
  const email = values.email.trim();
  if (!email) errors.email = 'Enter your email.';
  else if (!EMAIL.test(email)) errors.email = 'That doesn’t look like an email address.';
  else if (email.length > LIMITS.email) errors.email = tooLong(LIMITS.email);

  const name = values.name.trim();
  if (!name) errors.name = 'Enter your name.';
  else if (name.length > LIMITS.name) errors.name = tooLong(LIMITS.name);

  if (values.kind !== 'individual' && values.kind !== 'company') errors.kind = 'Choose whether you’re signing up for yourself or for a company.';
  if (values.kind === 'company') {
    const company = values.company.trim();
    if (!company) errors.company = 'Enter the company’s name.';
    else if (company.length > LIMITS.company) errors.company = tooLong(LIMITS.company);
  }

  for (const field of ['role', 'use_case', 'source'] as const) {
    if (values[field].trim().length > LIMITS[field]) errors[field] = tooLong(LIMITS[field]);
  }
  if (!values.consent) errors.consent = 'Agree to be contacted about Shurly to join the waitlist.';
  return errors;
}

const optional = (value: string) => value.trim() || null;

/** The request: trimmed, empty answers as null, and no company for an individual. */
export function waitlistBody(values: WaitlistValues): WaitlistBody {
  const company = values.kind === 'company';
  return {
    email: values.email.trim(),
    name: values.name.trim(),
    kind: company ? 'company' : 'individual',
    company: company ? optional(values.company) : null,
    company_size: company ? optional(values.company_size) : null,
    role: optional(values.role),
    use_case: optional(values.use_case),
    source: optional(values.source),
    consent: true,
    website: optional(values.website),
  };
}
