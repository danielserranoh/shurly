// "Send feedback" in the account menu and the phone's menu (the dogfood, ROADMAP 5.6.1): an email to the team, opened
// in the person's own mail app, with the page they sent it from. By its path only: a query can hold a link's code or a
// campaign's id, and a fragment a tab, which aren't the team's business. AppLayout builds it at build time, from the
// page's own path, so a query can't get in.

/** A mailto: link to `email`, with a subject and, below room to write, the page's path. */
export function feedbackHref(email: string, path: string): string {
  const page = path.split(/[?#]/)[0] || '/';
  // %20 for spaces and %0D%0A for line breaks, as RFC 6068 has them: mail apps read "+" as a plus.
  const subject = encodeURIComponent('Shurly feedback');
  const body = encodeURIComponent(`\r\n\r\nPage: ${page}`);
  return `mailto:${email}?subject=${subject}&body=${body}`;
}
