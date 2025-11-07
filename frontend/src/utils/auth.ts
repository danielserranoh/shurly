// Authentication utilities for managing JWT tokens

const TOKEN_KEY = 'shurly_auth_token';

/**
 * Store authentication token in localStorage
 */
export function setToken(token: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

/**
 * Get authentication token from localStorage
 */
export function getToken(): string | null {
  if (typeof window !== 'undefined') {
    return localStorage.getItem(TOKEN_KEY);
  }
  return null;
}

/**
 * Remove authentication token from localStorage
 */
export function removeToken(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY);
  }
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
  return getToken() !== null;
}

/**
 * Logout user by removing token and redirecting to login
 */
export function logout(): void {
  removeToken();
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
}

/**
 * Redirect to login page if not authenticated
 */
export function requireAuth(): void {
  if (typeof window !== 'undefined' && !isAuthenticated()) {
    window.location.href = '/login';
  }
}
