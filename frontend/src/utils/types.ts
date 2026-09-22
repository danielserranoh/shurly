// API response/request types — mirror server/schemas/*.py. Datetimes are ISO strings.

export type URLType = 'standard' | 'custom' | 'campaign';

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  created_at: string;
  api_key?: string | null;
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
}

export interface CampaignListResponse {
  campaigns: Campaign[];
  total: number;
}

export interface CreateCampaignRequest {
  name: string;
  original_url: string;
  csv_data: string;
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
}

export interface WeeklyStatsResponse {
  short_code: string;
  stats: WeeklyStat[];
  total_clicks: number;
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
