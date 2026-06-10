import { TopBar } from "@/components/top-bar"
import { PageHeader } from "@/components/page-header"
import { ActivityFeed } from "@/components/activity-feed"
import { agentMetrics } from "@/lib/axolotl-data"
import { Activity, ShieldCheck, Zap, GitPullRequestArrow } from "lucide-react"

export default function ActivityPage() {
  const headline = [
    { label: "Failures Detected", value: agentMetrics.failuresDetected, icon: Activity, tone: "text-destructive" },
    { label: "Fixes Generated", value: agentMetrics.fixesGenerated, icon: Zap, tone: "text-chart-4" },
    { label: "MRs Raised", value: agentMetrics.mergeRequestsRaised, icon: GitPullRequestArrow, tone: "text-primary" },
    { label: "Success Rate", value: `${agentMetrics.successRate}%`, icon: ShieldCheck, tone: "text-chart-3" },
  ]

  const breakdown = [
    { label: "Pipelines monitored", value: agentMetrics.pipelinesMonitored.toLocaleString() },
    { label: "Human approved", value: agentMetrics.humanApproved },
    { label: "Auto-merged", value: agentMetrics.autoMerged },
    { label: "Avg. time to fix", value: agentMetrics.avgTimeToFix },
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
                  {s.value}
                </div>
              </div>
            ))}
          </div>
        }
      />
      <main className="mx-auto w-full max-w-[1600px] px-4 py-6 md:px-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
          <section>
            <h2 className="mb-4 text-sm font-semibold text-foreground">Event timeline</h2>
            <ActivityFeed />
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
      </main>
    </div>
  )
}
