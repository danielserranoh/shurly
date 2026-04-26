// API utilities for making authenticated requests

import { getToken } from './auth';
import type { ApiError } from './types';

// API base URL - defaults to backend on localhost:8000
const API_BASE_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';

export interface FetchOptions extends RequestInit {
  requiresAuth?: boolean;
}

/**
 * Enhanced fetch wrapper that handles authentication and error responses
 */
export async function apiFetch<T>(
  endpoint: string,
  options: FetchOptions = {}
): Promise<T> {
  const { requiresAuth = false, headers = {}, ...rest } = options;

  const url = endpoint.startsWith('http')
    ? endpoint
    : `${API_BASE_URL}${endpoint}`;

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(headers as Record<string, string>),
  };

  // Add authentication token if required
  if (requiresAuth) {
    const token = getToken();
    if (token) {
      requestHeaders['Authorization'] = `Bearer ${token}`;
    } else {
      throw new Error('Authentication required');
    }
  }

  try {
    const response = await fetch(url, {
      ...rest,
      headers: requestHeaders,
    });

    // Handle non-OK responses
    if (!response.ok) {
      const errorData: ApiError = await response.json().catch(() => ({
        detail: 'An error occurred',
      }));

      const errorMessage = typeof errorData.detail === 'string'
        ? errorData.detail
        : Array.isArray(errorData.detail)
        ? errorData.detail.map(e => e.msg).join(', ')
        : 'An error occurred';

      throw new Error(errorMessage);
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return {} as T;
    }

    return await response.json();
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error('Network error occurred');
  }
}

/**
 * Convenience method for GET requests
 */
export async function apiGet<T>(
  endpoint: string,
  requiresAuth = false
): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'GET', requiresAuth });
}

/**
 * Convenience method for POST requests
 */
export async function apiPost<T>(
  endpoint: string,
  data: any,
  requiresAuth = false
): Promise<T> {
  return apiFetch<T>(endpoint, {
    method: 'POST',
    body: JSON.stringify(data),
    requiresAuth,
  });
}

/**
 * Convenience method for PUT requests
 */
export async function apiPut<T>(
  endpoint: string,
  data: any,
  requiresAuth = false
): Promise<T> {
  return apiFetch<T>(endpoint, {
    method: 'PUT',
    body: JSON.stringify(data),
    requiresAuth,
  });
}

/**
 * Convenience method for DELETE requests
 */
export async function apiDelete<T>(
  endpoint: string,
  requiresAuth = false
): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'DELETE', requiresAuth });
}

/**
 * Download file from API (e.g., CSV export)
 */
export async function apiDownload(
  endpoint: string,
  filename: string,
  requiresAuth = false
): Promise<void> {
  const token = getToken();
  const url = endpoint.startsWith('http')
    ? endpoint
    : `${API_BASE_URL}${endpoint}`;

  const headers: Record<string, string> = {};
  if (requiresAuth && token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, { headers });

  if (!response.ok) {
    throw new Error('Failed to download file');
  }

  const blob = await response.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(downloadUrl);
}
