// API response/request types — mirror server/schemas/*.py. Datetimes are ISO strings.

export type URLType = 'standard' | 'custom' | 'campaign';

/** Phase 3.14: an organization link or campaign, or a personal one only its creator sees. */
export type Visibility = 'organization' | 'personal';

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  created_at: string;
  /** Phase 6.3: whether there's an API key and how it starts. The key itself is shown once, by generate. */
  has_api_key?: boolean;
  api_key_prefix?: string | null;
  /** Phase 3.13: how the account signs in. Absent from APIs older than Google sign-in. */
  has_password?: boolean;
  has_google?: boolean;
  /** Phase 3.12. Absent from APIs older than the profile. */
  profile?: Profile;
}

/** Phase 3.12: each field is null until the person sets it. */
export interface Profile {
  first_name: string | null;
  last_name: string | null;
  /** ISO 3166-1 alpha-2, e.g. "ES". */
  country: string | null;
  /** IANA name, e.g. "Atlantic/Canary". */
  timezone: string | null;
  /** Changes with each upload; null without an avatar. Absent from APIs older than the avatar. */
  avatar_version?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface Tag {
  id: string;
  name: string; // lowercase, unique
  display_name: string;
  color: string; // "blue-500" style for predefined categories, "gray-500" for user tags
  is_predefined: boolean;
  usage_count: number;
  created_at: string;
}

export interface TagListResponse {
  tags: Tag[];
  total: number;
}

export interface ShortLink {
  id: string;
  short_code: string;
  short_url: string | null;
  /** Phase 8.3: the link's domain; one code can name links on several. Absent from older APIs. */
  domain?: string | null;
  original_url: string;
  url_type: URLType;
  title: string | null;
  forward_parameters: boolean;
  og_title: string | null;
  og_description: string | null;
  og_image_url: string | null;
  og_fetched_at: string | null;
  last_click_at: string | null;
  valid_since: string | null;
  valid_until: string | null;
  max_visits: number | null;
  crawlable: boolean;
  tags: Tag[];
  click_count: number;
  campaign_id: string | null;
  /** Its campaign's name, for a campaign link. */
  campaign_name?: string | null;
  user_data: Record<string, string> | null;
  created_at: string;
  updated_at: string;
  warning?: string | null;
  visibility: Visibility;
  created_by_email: string | null;
  /** Phase 3.12: the creator's name, from their profile; null without one, absent from older APIs. */
  created_by_first_name?: string | null;
  created_by_last_name?: string | null;
}

export interface LinkListResponse {
  urls: ShortLink[];
  total: number;
}

export interface CreateLinkRequest {
  url: string;
  title?: string;
  forward_parameters?: boolean;
  og_title?: string;
  og_description?: string;
  og_image_url?: string;
  valid_since?: string | null;
  valid_until?: string | null;
  max_visits?: number | null;
  crawlable?: boolean;
  custom_code?: string;
  visibility?: Visibility;
}

export type UpdateLinkRequest = Partial<
  Pick<
    ShortLink,
    | 'title'
    | 'original_url'
    | 'forward_parameters'
    | 'og_title'
    | 'og_description'
    | 'og_image_url'
    | 'valid_since'
    | 'valid_until'
    | 'max_visits'
    | 'crawlable'
  >
>;

export interface LinkMetadata {
  og_title: string | null;
  og_description: string | null;
  og_image_url: string | null;
}

export interface PreviewMetadata extends LinkMetadata {
  og_url: string;
  has_custom_preview: boolean;
  fetched_at: string | null;
}

// Campaigns

export interface CampaignLink {
  id: string;
  short_code: string;
  short_url: string | null;
  user_data: Record<string, string> | null;
  created_at: string;
}

export interface Campaign {
  id: string;
  name: string;
  original_url: string;
  csv_columns: string[];
  url_count: number;
  created_at: string;
  tags: Tag[];
  urls?: CampaignLink[] | null;
  visibility: Visibility;
  created_by_email: string | null;
  /** Phase 3.12: the creator's name, from their profile; null without one, absent from older APIs. */
  created_by_first_name?: string | null;
  created_by_last_name?: string | null;
}

export interface CampaignListResponse {
  campaigns: Campaign[];
  total: number;
}

export interface CreateCampaignRequest {
  name: string;
  original_url: string;
  csv_data: string;
  visibility?: Visibility;
}

// Analytics

export interface DailyStat {
  date: string; // YYYY-MM-DD
  clicks: number;
}

export interface WeeklyStat {
  week_start: string;
  week_end: string;
  clicks: number;
}

export interface DailyStatsResponse {
  short_code: string;
  stats: DailyStat[];
  total_clicks: number;
  /** The IANA zone the days are counted in: the viewer's, else UTC. Absent from older APIs. */
  timezone?: string;
}

export interface WeeklyStatsResponse {
  short_code: string;
  stats: WeeklyStat[];
  total_clicks: number;
  /** The IANA zone the days are counted in: the viewer's, else UTC. Absent from older APIs. */
  timezone?: string;
}

export interface GeoStat {
  country: string;
  clicks: number;
}

export interface GeoStatsResponse {
  short_code: string;
  stats: GeoStat[];
  total_clicks: number;
  period_days: number;
}

// ---------------------------------------------------------------------------
// Phase 3.16 — a link's analytics (ROADMAP 3.16.1, the contract)
// ---------------------------------------------------------------------------

/** What every period-bound response starts with: the range counted, after `period` or clipping. */
export interface CountedRange {
  from: string;
  to: string;
  timezone: string;
}

/** A link's responses name it. */
export interface LinkIdentity {
  short_code: string;
  domain: string | null;
}

/** A campaign's responses name it (3.17). */
export interface CampaignIdentity {
  campaign_id: string;
  campaign_name: string;
}

export type AnalyticsRange = LinkIdentity & CountedRange;

/** A visit is one kind: a click, an email open (the pixel), or a bot's. */
export type VisitKind = 'click' | 'open' | 'bot';
/** The filter of /breakdown, /visits and /visits.csv. */
export type VisitType = 'clicks' | 'opens' | 'bots' | 'all';

/** GET …/totals: the all-time numbers. */
export interface LinkTotals {
  short_code: string;
  domain: string | null;
  timezone: string;
  clicks: number;
  opens: number;
  countries: number;
  last_click_at: string | null;
}

/** GET …/timeseries, a link's or a campaign's: the same shape. */
export interface Timeseries extends CountedRange {
  group_by: 'day' | 'week' | 'month';
  clicks: number;
  opens: number;
  stats: Array<{ start: string; end: string; clicks: number; opens: number }>;
  hour_of_day: Array<{ hour: number; clicks: number; opens: number }>;
  day_of_week: Array<{ day: number; clicks: number; opens: number }>;
}

export interface BreakdownEntry {
  name: string;
  count: number;
  /** 0–1, four decimals. */
  share: number;
}

/** GET …/breakdown, a link's or a campaign's. */
export interface Breakdown extends CountedRange {
  type: VisitType;
  total: number;
  os: BreakdownEntry[];
  browsers: BreakdownEntry[];
  devices: BreakdownEntry[];
  referrers: BreakdownEntry[];
  /** ISO codes, and "Unknown". */
  countries: BreakdownEntry[];
  /**
   * Phase 8.4: English names, each with its country's code. "Unknown" and a campaign's "Other cities" have none.
   * Null for a campaign link (one recipient's visits); absent from an API before 8.4.
   */
  cities?: CityEntry[] | null;
}

export interface CityEntry extends BreakdownEntry {
  country: string | null;
}

export interface LinkVisit {
  visited_at: string;
  kind: VisitKind;
  country: string;
  browser: string;
  os: string;
  device: string;
  referrer: string;
}

/** GET …/visits: a link's only (a campaign has none, on purpose). */
export interface Visits extends CountedRange {
  type: VisitType;
  total: number;
  page: number;
  page_size: number;
  pages: number;
  visits: LinkVisit[];
}

export interface LinkTimeseries extends Timeseries, LinkIdentity {}
export interface LinkBreakdown extends Breakdown, LinkIdentity {}
export interface LinkVisits extends Visits, LinkIdentity {}

// ---------------------------------------------------------------------------
// Phase 3.17 — a campaign's analytics (ROADMAP 3.17.1, the contract)
// ---------------------------------------------------------------------------

/** GET …/campaigns/{id}/totals: all time. Rates are 0–1. */
export interface CampaignTotals extends CampaignIdentity {
  timezone: string;
  recipients: number;
  clicks: number;
  opens: number;
  /** Recipients with at least one click. */
  clicked: number;
  /** Recipients with at least one email open that isn't a bot's. */
  opened: number;
  click_rate: number;
  open_rate: number;
  countries: number;
  last_click_at: string | null;
}

export interface CampaignTimeseries extends Timeseries, CampaignIdentity {}
export interface CampaignBreakdown extends Breakdown, CampaignIdentity {}

/** A row of `/recipients`: one per personalized link, all time. Times are local, null without one. */
export interface CampaignRecipient {
  short_code: string;
  short_url: string;
  domain: string | null;
  user_data: Record<string, string>;
  clicks: number;
  opens: number;
  first_click_at: string | null;
  last_click_at: string | null;
  last_open_at: string | null;
}

export type RecipientFilterName = 'all' | 'clicked' | 'opened' | 'none';

/** GET …/recipients: a page of them, filtered, searched and sorted by the API. */
export interface CampaignRecipients extends CampaignIdentity {
  timezone: string;
  filter: RecipientFilterName;
  q: string;
  sort: 'clicks' | 'opens' | 'last_click' | 'code';
  order: 'asc' | 'desc';
  total: number;
  page: number;
  page_size: number;
  pages: number;
  recipients: CampaignRecipient[];
  /** How many match each filter, honouring `q` but not `filter`: the counts on the filter's options. */
  counts?: Record<RecipientFilterName, number>;
}

export interface CampaignRecipientStat {
  user_data: Record<string, string>;
  short_code: string;
  clicks: number;
  unique_ips: number;
  last_clicked: string | null;
}

export interface CampaignSummary {
  campaign_id: string;
  campaign_name: string;
  original_url: string;
  total_urls: number;
  total_clicks: number;
  unique_ips: number;
  click_through_rate: number; // % of links clicked at least once
  top_performers: CampaignRecipientStat[];
  daily_timeline: DailyStat[];
  /** The IANA zone the days are counted in: the viewer's, else UTC. Absent from older APIs. */
  timezone?: string;
}

export interface CampaignUsersResponse {
  campaign_id: string;
  campaign_name: string;
  users: CampaignRecipientStat[];
  total_users: number;
}

export interface TopLink {
  short_code: string;
  short_url?: string;
  domain?: string;
  title?: string | null;
  original_url: string;
  url_type: URLType;
  clicks: number;
}

export interface OverviewStats {
  total_urls: number;
  total_campaigns: number;
  total_clicks: number;
  total_unique_visitors: number;
  recent_clicks_7d: number;
  top_urls: TopLink[];
  recent_activity: DailyStat[];
  /** The IANA zone the days are counted in: the viewer's, else UTC. Absent from older APIs. */
  timezone?: string;
}

// "Typos & broken links" (ROADMAP 3.10.4): orphan visits by the path tried, from the API.

/** A link the path was probably meant for: one edit away, or the same code but for case. */
export interface OrphanSuggestion {
  short_code: string;
  domain: string;
  short_url: string;
  title: string | null;
}

export interface OrphanGroup {
  attempted_path: string;
  visits: number;
  first_seen: string;
  last_seen: string;
  /** Up to 3, the likeliest first. */
  did_you_mean: OrphanSuggestion[];
}

export interface OrphanGroupsResponse {
  from: string;
  to: string;
  timezone: string;
  total_visits: number;
  total_paths: number;
  page: number;
  page_size: number;
  pages: number;
  groups: OrphanGroup[];
}

// Redirect rules (Phase 3.10.2)

export type RuleConditionType =
  | 'device'
  | 'language'
  | 'query_param'
  | 'before_date'
  | 'after_date'
  | 'browser';

export interface RuleCondition {
  type: RuleConditionType;
  value: string;
  [key: string]: unknown;
}

export interface RedirectRule {
  id: string;
  url_id: string;
  priority: number;
  conditions: RuleCondition[];
  target_url: string;
  created_at: string;
}

export interface ApiKeyResponse {
  api_key: string;
  scope: string;
}

export interface MessageResponse {
  message: string;
}

// Organization (Phase 3.14)

export type OrgRole = 'owner' | 'admin' | 'member';

/** GET /api/v1/organization: the caller's organization, and their role in it. */
export interface Organization {
  id: string;
  name: string;
  google_domain: string | null;
  role: OrgRole;
  /** Phase 3.14.4 — changes with each upload; null without a logo. Absent from APIs older than the logo. */
  logo_version?: string | null;
}

export interface OrgMember {
  user_id: string;
  email: string;
  /** Phase 3.12: from their profile; null without one, absent from older APIs. */
  first_name?: string | null;
  last_name?: string | null;
  role: OrgRole;
  joined_at: string;
}

/** POST /api/v1/organization/adopt-personal-links: links (a campaign's included) and campaigns moved. */
export interface AdoptedLinks {
  links: number;
  campaigns: number;
}

/** Phase 3.14.3: someone removed from the organization, and what they still own that an owner can move. */
export interface RemovedMember {
  user_id: string;
  email: string;
  /** Phase 3.12: from their profile; null without one, absent from older APIs. */
  first_name?: string | null;
  last_name?: string | null;
  /** Personal links, a campaign's included: what adopt-personal-links would move. */
  links: number;
  campaigns: number;
}
