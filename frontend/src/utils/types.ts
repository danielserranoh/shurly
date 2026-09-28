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
export interface AnalyticsRange {
  short_code: string;
  domain: string | null;
  from: string;
  to: string;
  timezone: string;
}

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

export interface LinkTimeseries extends AnalyticsRange {
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

export interface LinkBreakdown extends AnalyticsRange {
  type: VisitType;
  total: number;
  os: BreakdownEntry[];
  browsers: BreakdownEntry[];
  devices: BreakdownEntry[];
  referrers: BreakdownEntry[];
  /** ISO codes, and "Unknown". */
  countries: BreakdownEntry[];
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

export interface LinkVisits extends AnalyticsRange {
  type: VisitType;
  total: number;
  page: number;
  page_size: number;
  pages: number;
  visits: LinkVisit[];
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

export interface OrphanVisit {
  id: string;
  type: 'base_url' | 'invalid_short_url' | 'regular_404';
  attempted_path: string;
  ip: string | null;
  user_agent: string | null;
  referer: string | null;
  created_at: string | null;
}

export interface OrphanVisitsResponse {
  total: number;
  items: OrphanVisit[];
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
