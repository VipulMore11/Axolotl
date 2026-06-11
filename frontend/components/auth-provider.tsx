"use client"

import React, { createContext, useContext, useEffect, useState } from "react"
import { usePathname, useRouter } from "next/navigation"
import { getUserProfile, isAuthenticated, logout } from "@/lib/auth"

interface User {
  id: string
  gitlab_user_id: number
  username: string
  name: string
  avatar_url?: string
}

interface AuthContextType {
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  logout: () => void
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  isAuthenticated: false,
  logout: () => {},
})

export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const pathname = usePathname()
  const router = useRouter()

  useEffect(() => {
    // Don't check auth on public pages (login, callback)
    if (pathname === "/login" || pathname === "/auth/callback") {
      setIsLoading(false)
      return
    }

    let isMounted = true

    async function checkAuth() {
      if (!isAuthenticated()) {
        router.push("/login")
        return
      }

      const profile = await getUserProfile()
      if (isMounted) {
        if (profile) {
          setUser(profile)
        } else {
          router.push("/login")
        }
        setIsLoading(false)
      }
    }

    checkAuth()

    return () => {
      isMounted = false
    }
  }, [pathname, router])

  const handleLogout = () => {
    logout()
    setUser(null)
  }

  // Allow rendering of public routes without blocking
  if ((pathname === "/login" || pathname === "/auth/callback") && !user) {
    return <AuthContext.Provider value={{ user: null, isLoading: false, isAuthenticated: false, logout: handleLogout }}>{children}</AuthContext.Provider>
  }

  // Show nothing or a loader while validating session on protected routes
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <div className="flex flex-col items-center gap-4">
          <div className="size-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground animate-pulse">Authenticating...</p>
        </div>
      </div>
    )
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, isAuthenticated: !!user, logout: handleLogout }}>
      {children}
    </AuthContext.Provider>
  )
}
