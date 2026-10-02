// Site-wide configuration. Values that differ per deployment come from PUBLIC_* env vars.

import { API_BASE_URL } from '@/utils/api';

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export const site = {
  name: 'Shurly',
  tagline: 'Send the link. Know who opened it.',
  description: 'Trackable short links for small marketing teams.',
  /**
   * Host shown in front of back-halves ("go.griddo.io/"): PUBLIC_SHORT_DOMAIN. Production sets it (go.griddo.io),
   * since the API lives on shurly.griddo.io. The API's host is only the fallback,
   * right where the API also serves the redirects, as in local development.
   */
  shortDomain: (import.meta.env.PUBLIC_SHORT_DOMAIN as string | undefined) || hostOf(API_BASE_URL),
  apiDocsUrl: `${API_BASE_URL}/docs`,
  /** Where AI assistants connect (Phase 5.9), with the trailing slash they need. */
  mcpUrl: __SHURLY_MCP_URL__,
  /** Optional links for the open-source / sponsor strip on the landing page. Hidden when empty. */
  sourceUrl: (import.meta.env.PUBLIC_SOURCE_URL as string | undefined) || '',
  sponsorUrl: (import.meta.env.PUBLIC_SPONSOR_URL as string | undefined) || '',
  /** Where "Send feedback" writes (the dogfood, 5.6.1): the team's inbox. */
  supportEmail: 'support@griddo.io',
};

export interface Plan {
  id: 'free' | 'pro';
  name: string;
  price: string;
  cadence: string;
  blurb: string;
  features: string[];
  status: 'available' | 'coming-soon';
}

// Limits follow the UX brief (§7). Enforcement needs billing support in the API, so the
// app does not block anything yet — see design/DESIGN_SYSTEM.md → Paywall.
export const plans: Plan[] = [
  {
    id: 'free',
    name: 'Free',
    price: '$0',
    cadence: 'forever',
    blurb: 'Everything a small team needs to start tracking.',
    features: ['50 active links', '1,000 clicks a month', 'Custom back-halves', 'CSV campaigns', 'Up to 10 tags', '7-day analytics'],
    status: 'available',
  },
  {
    id: 'pro',
    name: 'Pro',
    price: 'Soon',
    cadence: '',
    blurb: 'For teams that live in their links.',
    features: [
      'Unlimited links and clicks',
      'Social preview editing',
      'Click notifications in Slack, Telegram & more',
      '30/90-day and custom analytics ranges',
      'Branded QR codes',
      'API & MCP access',
    ],
    status: 'coming-soon',
  },
];
