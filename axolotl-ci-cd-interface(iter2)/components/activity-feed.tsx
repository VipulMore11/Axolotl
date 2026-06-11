import { activityFeed, type ActivityEvent } from "@/lib/axolotl-data"
import { Badge } from "@/components/ui/badge"
import {
  AlertTriangle,
  Brain,
  Wrench,
  GitMerge,
  GitPullRequestArrow,
  CheckCircle2,
  XCircle,
} from "lucide-react"

const config: Record<
  ActivityEvent["type"],
  { icon: typeof Brain; ring: string; label: string }
> = {
  detection: { icon: AlertTriangle, ring: "border-destructive/40 bg-destructive/15 text-destructive", label: "Detection" },
  analysis: { icon: Brain, ring: "border-accent/40 bg-accent/15 text-accent", label: "Analysis" },
  fix: { icon: Wrench, ring: "border-chart-4/40 bg-chart-4/15 text-chart-4", label: "Fix" },
  "merge-request": { icon: GitPullRequestArrow, ring: "border-primary/40 bg-primary/15 text-primary", label: "Merge Request" },
  approval: { icon: CheckCircle2, ring: "border-primary/40 bg-primary/15 text-primary", label: "Approval" },
  merged: { icon: GitMerge, ring: "border-chart-3/40 bg-chart-3/15 text-chart-3", label: "Merged" },
  rejected: { icon: XCircle, ring: "border-destructive/40 bg-destructive/15 text-destructive", label: "Rejected" },
}

export function ActivityFeed() {
  return (
    <ol className="relative">
      {activityFeed.map((ev, i) => {
        const c = config[ev.type]
        const Icon = c.icon
        const last = i === activityFeed.length - 1
        return (
          <li key={ev.id} className="relative flex gap-4 pb-6 last:pb-0">
            {!last && (
              <span className="absolute left-[19px] top-10 h-[calc(100%-1.5rem)] w-px bg-border" />
            )}
            <span
              className={`z-10 flex size-10 shrink-0 items-center justify-center rounded-full border ${c.ring}`}
            >
              <Icon className="size-4" />
            </span>
            <div className="min-w-0 flex-1 rounded-lg border border-border bg-card px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-foreground">{ev.summary}</p>
                <Badge variant="outline" className="font-mono text-[10px] text-muted-foreground">
                  {ev.project}
                </Badge>
                <Badge variant="outline" className="font-mono text-[10px] text-accent/80">
                  {ev.pipeline}
                </Badge>
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                  {ev.time}
                </span>
              </div>
              <p className="mt-1 text-pretty text-xs leading-relaxed text-muted-foreground">
                {ev.detail}
              </p>
              {ev.model && (
                <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11px] text-muted-foreground">
                  <span className="text-accent">{ev.model}</span>
                  {ev.confidence != null && (
                    <span className="flex items-center gap-1.5">
                      confidence
                      <span className="text-chart-3">{ev.confidence}%</span>
                    </span>
                  )}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
