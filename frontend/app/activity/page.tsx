"use client"

import { useEffect, useState } from "react"
import { TopBar } from "@/components/top-bar"
import { PageHeader } from "@/components/page-header"
import { ActivityFeed } from "@/components/activity-feed"
import { getActivityEvents, getActivityMetrics, type APIActivityEvent } from "@/lib/api"
import { Activity, ShieldCheck, Zap, GitPullRequestArrow, Loader2 } from "lucide-react"

export default function ActivityPage() {
  const [events, setEvents] = useState<APIActivityEvent[]>([])
  const [metrics, setMetrics] = useState<{
    failures_detected: number
    fixes_generated: number
    merge_requests_raised: number
    success_rate: number
    human_approved: number
    auto_merged: number
  } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [evData, metData] = await Promise.all([
          getActivityEvents(),
          getActivityMetrics(),
        ])
        setEvents(evData.events)
        setMetrics(metData.metrics)
      } catch (e) {
        console.error("Failed to load activity:", e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const headline = [
    { label: "Failures Detected", value: metrics?.failures_detected ?? 0, icon: Activity, tone: "text-destructive" },
    { label: "Fixes Generated", value: metrics?.fixes_generated ?? 0, icon: Zap, tone: "text-chart-4" },
    { label: "MRs Raised", value: metrics?.merge_requests_raised ?? 0, icon: GitPullRequestArrow, tone: "text-primary" },
    { label: "Success Rate", value: metrics ? `${metrics.success_rate}%` : "—", icon: ShieldCheck, tone: "text-chart-3" },
  ]

  const breakdown = [
    { label: "Human approved", value: metrics?.human_approved ?? 0 },
    { label: "Auto-merged", value: metrics?.auto_merged ?? 0 },
  ]

  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <PageHeader
        title="Agent Activity"
        description="A chronological trace of everything Axolotl has done — from detecting failures and reasoning with Gemini, to raising merge requests and recording human decisions."
        meta={
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {headline.map((s) => (
              <div key={s.label} className="rounded-lg border border-border bg-card px-4 py-3">
                <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                  <s.icon className={`size-3.5 ${s.tone}`} />
                  {s.label}
                </div>
                <div className="mt-1 font-mono text-2xl font-semibold text-foreground">
                  {loading ? "—" : s.value}
                </div>
              </div>
            ))}
          </div>
        }
      />
      <main className="mx-auto w-full max-w-[1600px] px-4 py-6 md:px-6">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading activity...
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
            <section>
              <h2 className="mb-4 text-sm font-semibold text-foreground">Event timeline</h2>
              {events.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-card px-4 py-16 text-center">
                  <Activity className="size-8 text-muted-foreground/40 mb-2" />
                  <p className="text-sm text-muted-foreground">
                    No activity events yet. Events will appear here when the agent detects and fixes pipeline failures.
                  </p>
                </div>
              ) : (
                <ActivityFeed events={events} />
              )}
            </section>

            <aside className="lg:sticky lg:top-[3.75rem] lg:self-start">
              <div className="rounded-lg border border-border bg-card">
                <div className="border-b border-border px-4 py-3">
                  <h3 className="text-sm font-semibold text-foreground">Lifetime metrics</h3>
                </div>
                <ul className="divide-y divide-border/60">
                  {breakdown.map((b) => (
                    <li key={b.label} className="flex items-center justify-between px-4 py-3">
                      <span className="text-sm text-muted-foreground">{b.label}</span>
                      <span className="font-mono text-sm font-medium text-foreground">{b.value}</span>
                    </li>
                  ))}
                </ul>
                <div className="border-t border-border px-4 py-3">
                  <div className="mb-1.5 flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Human-in-the-loop coverage</span>
                    <span className="font-mono text-chart-3">100%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                    <span className="block h-full w-full rounded-full bg-chart-3" />
                  </div>
                  <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                    Every fix required explicit reviewer approval before merge.
                  </p>
                </div>
              </div>
            </aside>
          </div>
        )}
      </main>
    </div>
  )
}
