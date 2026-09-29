// The dashboard's welcome card for new members (the dogfood, ROADMAP 5.6): where to start, for an account in its
// first days, until it's dismissed. Links are the organization's (3.14), so a new member's list isn't empty and
// the empty state can't do this job.

/** How long an account counts as new: the rollout may be gradual. */
export const WELCOME_DAYS = 14;
const DAY_MS = 86_400_000;

/** An account younger than WELCOME_DAYS (`created_at` from /auth/me) that hasn't dismissed the card. */
export function shouldWelcome(createdAt: string | null | undefined, dismissed: boolean, now: number = Date.now()): boolean {
  if (dismissed || !createdAt) return false;
  const created = Date.parse(createdAt);
  return !Number.isNaN(created) && now - created < WELCOME_DAYS * DAY_MS;
}

/** Where the dismissal is kept (localStorage), per account: someone else on this browser is still welcomed. */
export const welcomeDismissedKey = (userId: string) => `shurly_welcome_dismissed:${userId}`;

/** Whose links are whose: the organization's, by its name, for a member; an account outside one keeps its own. */
export function sharingLine(organization: { name: string } | null): string {
  return organization
    ? `Links you make belong to ${organization.name}, so your team sees them and you see theirs. Make one personal when it’s just for you.`
    : 'Your links are personal to you.';
}
