/**
 * Authentication utilities for the frontend.
 * Handles token storage, user session retrieval, and auth state management.
 */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

/**
 * Get the JWT token from localStorage
 */
export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem("axolotl_token")
}

/**
 * Save the JWT token to localStorage
 */
export function setToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("axolotl_token", token)
  }
}

/**
 * Remove the JWT token
 */
export function removeToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("axolotl_token")
  }
}

/**
 * Check if the user is authenticated (has a token)
 */
export function isAuthenticated(): boolean {
  return !!getToken()
}

/**
 * Fetch the authenticated user profile from the backend
 */
export async function getUserProfile() {
  const token = getToken()
  if (!token) return null

  try {
    const res = await fetch(`${API_BASE_URL}/auth/me`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
    
    if (!res.ok) {
      if (res.status === 401) {
        removeToken()
      }
      return null
    }
    
    return await res.json()
  } catch (error) {
    console.error("Failed to fetch user profile:", error)
    return null
  }
}

/**
 * Logout the user
 */
export async function logout(): Promise<void> {
  // Optional: notify backend
  const token = getToken()
  if (token) {
    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })
    } catch (e) {
      // Ignore backend errors on logout
    }
  }
  
  removeToken()
  if (typeof window !== "undefined") {
    window.location.href = "/login"
  }
}
