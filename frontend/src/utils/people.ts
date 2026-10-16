// People in the organization, by name (Phase 3.12): their profile's first and last name,
// and their email when they gave neither.

export interface Person {
  email: string;
  first_name?: string | null;
  last_name?: string | null;
}

export function hasName(person: Person): boolean {
  return Boolean(person.first_name?.trim() || person.last_name?.trim());
}

/** "Ana García", or the one name they gave; the email without either. */
export function personName(person: Person): string {
  if (!hasName(person)) return person.email;
  return [person.first_name, person.last_name]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(' ');
}

/** For a dialog's body: which account a name means, as two people can share one. Empty without a name. */
export function accountLine(person: Person): string {
  return hasName(person) ? `Their account is ${person.email}. ` : '';
}

// ---------------------------------------------------------------------------
// Phase 10.1 — service accounts: another system that makes links for the organization
// ---------------------------------------------------------------------------

/** A link's service account, as the API gives it: never its token. */
export interface ServiceAccountRef {
  id: string;
  display_name: string | null;
}

/** A service account's email is a placeholder (server/core/models/user.py), never shown. */
const SERVICE_EMAIL_DOMAIN = '@service.invalid';

export function isServiceEmail(email: string | null | undefined): boolean {
  return Boolean(email && email.toLowerCase().endsWith(SERVICE_EMAIL_DOMAIN));
}

export function serviceName(service: ServiceAccountRef): string {
  return service.display_name?.trim() || 'a service account';
}

/**
 * Who made a link, as "Created by …" ends: "Ana García via Propuestas Griddo" when a service made it
 * for Ana, the service's name when it acted for nobody (it's the creator), or just `creator`.
 */
export function createdBy(creator: string, creatorEmail: string | null | undefined, via: ServiceAccountRef | null | undefined): string {
  if (!via) return creator;
  if (isServiceEmail(creatorEmail)) return serviceName(via);
  return `${creator} via ${serviceName(via)}`;
}
