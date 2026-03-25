/**
 * Centralized token storage utility
 * Handles secure token storage and retrieval
 */

import type { SessionUser } from '@/features/auth/types/session-user';

export interface TokenData {
  idToken: string;
  refreshToken: string;
  expiresAt?: number; // Unix timestamp
}

class TokenStorage {
  public readonly AUTH_TOKEN_KEY = 'auth_token';
  public readonly REFRESH_TOKEN_KEY = 'refresh_token';
  public readonly TOKEN_EXPIRES_KEY = 'token_expires';
  public readonly USER_KEY = 'user';

  private getStorage(): Storage | null {
    if (typeof window === 'undefined') return null;
    const ls = (globalThis as any).localStorage as Storage | undefined;
    if (!ls) return null;
    if (typeof ls.getItem !== 'function') return null;
    return ls;
  }

  setUser(user: SessionUser): void {
    const storage = this.getStorage();
    if (!storage) return;
    storage.setItem(this.USER_KEY, JSON.stringify(user));
  }

  getUser(): SessionUser | null {
    const storage = this.getStorage();
    if (!storage) return null;

    const user = storage.getItem(this.USER_KEY);
    return user ? JSON.parse(user) : null;
  }
  /**
   * Store tokens securely
   */
  setTokens(tokenData: TokenData): void {
    try {
      const storage = this.getStorage();
      if (!storage) return;

      storage.setItem(this.AUTH_TOKEN_KEY, tokenData.idToken);
      storage.setItem(this.REFRESH_TOKEN_KEY, tokenData.refreshToken);

      // Calculate expiration time (default to 1 hour if not provided)
      const expiresAt = tokenData.expiresAt || Date.now() + 60 * 60 * 1000;
      storage.setItem(this.TOKEN_EXPIRES_KEY, expiresAt.toString());

      // Set secure cookie with proper flags
      this.setSecureCookie(this.AUTH_TOKEN_KEY, tokenData.idToken);
    } catch (error) {
      console.error('Failed to store tokens:', error);
    }
  }

  /**
   * Get auth token
   */
  getAuthToken(): string | null {
    try {
      const storage = this.getStorage();
      if (!storage) return null;
      return storage.getItem(this.AUTH_TOKEN_KEY);
    } catch (error) {
      console.error('Failed to retrieve auth token:', error);
      return null;
    }
  }

  /**
   * Get refresh token
   */
  getRefreshToken(): string | null {
    try {
      const storage = this.getStorage();
      if (!storage) return null;
      return storage.getItem(this.REFRESH_TOKEN_KEY);
    } catch (error) {
      console.error('Failed to retrieve refresh token:', error);
      return null;
    }
  }

  /**
   * Clear all stored tokens and user data
   */
  clearTokens(): void {
    try {
      const storage = this.getStorage();
      if (!storage) return;

      storage.removeItem(this.AUTH_TOKEN_KEY);
      storage.removeItem(this.REFRESH_TOKEN_KEY);
      storage.removeItem(this.TOKEN_EXPIRES_KEY);
      storage.removeItem(this.USER_KEY);

      // Clear auth cookie
      this.clearCookie(this.AUTH_TOKEN_KEY);
    } catch (error) {
      console.error('Failed to clear tokens:', error);
    }
  }

  /**
   * Set secure cookie with proper security flags
   */
  private setSecureCookie(name: string, value: string): void {
    if (typeof document === 'undefined' || typeof window === 'undefined') return;
    const maxAge = 30 * 24 * 60 * 60; // 30 days
    const secure = window.location.protocol === 'https:' ? '; secure' : '';

    document.cookie = `${name}=${value}; path=/; max-age=${maxAge}; samesite=strict${secure}`;
  }

  /**
   * Clear specific cookie
   */
  private clearCookie(name: string): void {
    if (typeof document === 'undefined') return;
    document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:01 GMT;`;
  }

  /**
   * Get token expiration time
   */
  getTokenExpiration(): number | null {
    try {
      const storage = this.getStorage();
      if (!storage) return null;

      const expiresAt = storage.getItem(this.TOKEN_EXPIRES_KEY);
      return expiresAt ? parseInt(expiresAt, 10) : null;
    } catch (error) {
      console.error('Failed to retrieve token expiration:', error);
      return null;
    }
  }

  /**
   * Check if token is expired or about to expire (within 5 minutes)
   */
  isTokenExpired(): boolean {
    const expiresAt = this.getTokenExpiration();
    if (!expiresAt) return true;

    const now = Date.now();
    const fiveMinutes = 5 * 60 * 1000;
    return now >= expiresAt - fiveMinutes;
  }

  /**
   * Check if user is authenticated (has valid, non-expired tokens)
   */
  isAuthenticated(): boolean {
    const hasTokens = !!(this.getAuthToken() && this.getRefreshToken());
    return hasTokens && !this.isTokenExpired();
  }
}

export const tokenStorage = new TokenStorage();
