// API Response Types

export interface User {
  id: number;
  email: string;
  is_active: boolean;
  created_at: string;
  api_key?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface RegisterResponse {
  id: number;
  email: string;
  is_active: boolean;
  created_at: string;
}

export interface URL {
  id: number;
  short_code: string;
  short_url: string;
  original_url: string;
  url_type: string;
  created_at: string;
  click_count?: number;
}

export interface URLListResponse {
  urls: URL[];
  total: number;
}

export interface CreateURLRequest {
  url: string;
}

export interface CreateCustomURLRequest {
  url: string;
  custom_code: string;
}

export interface CreateURLResponse extends URL {
  warning?: string;
}

export interface ApiError {
  detail: string | { msg: string; type: string }[];
}

// Campaign Types

export interface CampaignURL {
  id: string;
  short_code: string;
  short_url: string;
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
  urls?: CampaignURL[];
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

// Analytics Types

export interface DailyStats {
  date: string;
  clicks: number;
}

export interface WeeklyStats {
  week_start: string;
  week_end: string;
  clicks: number;
}

export interface GeoStats {
  country: string;
  clicks: number;
}

export interface GeoStatsResponse {
  stats: GeoStats[];
  total_countries: number;
}

export interface DailyStatsResponse {
  stats: DailyStats[];
  total_clicks: number;
}

export interface WeeklyStatsResponse {
  stats: WeeklyStats[];
  total_clicks: number;
}

export interface OverviewStats {
  total_urls: number;
  total_campaigns: number;
  total_clicks: number;
  unique_visitors: number;
  recent_clicks: number;
  top_urls: Array<{
    short_code: string;
    short_url: string;
    clicks: number;
  }>;
  daily_timeline: DailyStats[];
}
