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
