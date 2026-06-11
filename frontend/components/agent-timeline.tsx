import { agentStages, type StageState } from "@/lib/axolotl-data"
import { Check, Loader2, Circle, X } from "lucide-react"

function StageIcon({ state }: { state: StageState }) {
  if (state === "done")
    return (
      <span className="flex size-6 items-center justify-center rounded-full border border-chart-3/40 bg-chart-3/15 text-chart-3">
        <Check className="size-3.5" />
      </span>
    )
  if (state === "active")
    return (
      <span className="flex size-6 items-center justify-center rounded-full border border-primary/40 bg-primary/15 text-primary">
        <Loader2 className="size-3.5 animate-spin" />
      </span>
    )
  if (state === "error")
    return (
      <span className="flex size-6 items-center justify-center rounded-full border border-destructive/40 bg-destructive/15 text-destructive">
        <X className="size-3.5" />
      </span>
    )
  return (
    <span className="flex size-6 items-center justify-center rounded-full border border-border bg-secondary text-muted-foreground">
      <Circle className="size-2.5" />
    </span>
  )
}

export function AgentTimeline() {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">Agent Workflow</h2>
        <span className="font-mono text-xs text-muted-foreground">7 / 8 stages</span>
      </div>
      <ol className="px-4 py-2">
        {agentStages.map((stage, i) => (
          <li key={stage.key} className="relative flex gap-3 pb-1 pt-1">
            <div className="flex flex-col items-center">
              <StageIcon state={stage.state} />
              {i < agentStages.length - 1 && (
                <span
                  className={`my-0.5 w-px flex-1 ${
                    stage.state === "done" ? "bg-chart-3/30" : "bg-border"
                  }`}
                />
              )}
            </div>
            <div className="min-w-0 flex-1 pb-3">
              <div className="flex items-center justify-between gap-2">
                <p
                  className={`text-sm font-medium ${
                    stage.state === "pending" ? "text-muted-foreground" : "text-foreground"
                  }`}
                >
                  {stage.label}
                </p>
                {stage.durationMs != null && (
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                    {(stage.durationMs / 1000).toFixed(1)}s
                  </span>
                )}
                {stage.state === "active" && (
                  <span className="shrink-0 font-mono text-[11px] text-primary">live</span>
                )}
              </div>
              <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                {stage.description}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
