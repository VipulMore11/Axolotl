"use client"

import { useEffect, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { setToken } from "@/lib/auth"

function CallbackContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get("token")

  useEffect(() => {
    if (token) {
      setToken(token)

      if (typeof pendo !== "undefined") {
        pendo.track("login_completed", {
          auth_method: "gitlab_oauth",
        })
      }

      // Redirect to dashboard after a brief delay to allow token to settle
      setTimeout(() => {
        router.push("/")
      }, 500)
    } else {
      console.error("No token found in callback URL")
      router.push("/login")
    }
  }, [token, router])

  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="flex flex-col items-center gap-4">
        <div className="size-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground animate-pulse">Completing login...</p>
      </div>
    </div>
  )
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <div className="size-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    }>
      <CallbackContent />
    </Suspense>
  )
}
