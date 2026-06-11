"use client"

import { Badge } from "@/components/ui/badge"
import { CircleDot, Clock, GitCommit, Bot, ShieldCheck, Wifi, WifiOff } from "lucide-react"

interface PipelineHeaderProps {
  sessionId: string | null
  events: Array<{ event_type: string; message: string }>
  isConnected: boolean
}

export function PipelineHeader({ sessionId, events, isConnected }: PipelineHeaderProps) {
  if (!sessionId) {
    return (
      <section className="border-b border-border bg-card/40">
        <div className="px-4 py-5 md:px-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <h1 className="font-mono text-lg font-semibold text-foreground">
                Dashboard
              </h1>
              <Badge variant="outline" className="font-mono text-xs text-muted-foreground">
                idle
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {isConnected ? (
                <>
                  <span className="size-1.5 animate-pulse rounded-full bg-chart-3" />
                  <span className="text-chart-3">WebSocket live</span>
                </>
              ) : (
                <>
                  <span className="size-1.5 rounded-full bg-chart-4" />
                  <span className="text-chart-4">Connecting...</span>
                </>
              )}
            </div>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            No active pipeline fix session. The agent is monitoring your pipelines.
          </p>
        </div>
      </section>
    )
  }

  // Extract info from events
  const pipelineEvent = events.find((e) => e.event_type === "pipeline_failed")
  const analyzeEvent = events.find((e) => e.event_type === "generating_fix")
  const isComplete = events.some((e) => e.event_type === "waiting_approval" || e.event_type === "fix_succeeded")

  const stats = [
    {
      label: "Session",
      value: sessionId.replace("pipeline-", "#"),
      icon: CircleDot,
      tone: "text-primary",
    },
    {
      label: "Status",
      value: isComplete ? "Awaiting Approval" : "In Progress",
      icon: Clock,
      tone: isComplete ? "text-chart-4" : "text-accent",
    },
    {
      label: "Model",
      value: "gemini-2.5-pro",
      icon: Bot,
      tone: "text-foreground",
    },
    {
      label: "Connection",
      value: isConnected ? "Live" : "Offline",
      icon: isConnected ? Wifi : WifiOff,
      tone: isConnected ? "text-chart-3" : "text-destructive",
    },
  ]

  return (
    <section className="border-b border-border bg-card/40">
      <div className="px-4 py-5 md:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-mono text-lg font-semibold text-foreground">
                Pipeline {sessionId.replace("pipeline-", "#")}
              </h1>
              {isComplete ? (
                <Badge className="gap-1.5 border-primary/30 bg-primary/15 text-primary hover:bg-primary/15">
                  <span className="size-1.5 animate-pulse rounded-full bg-primary" />
                  Awaiting Approval
                </Badge>
              ) : (
                <Badge className="gap-1.5 border-accent/30 bg-accent/15 text-accent hover:bg-accent/15">
                  <span className="size-1.5 animate-pulse rounded-full bg-accent" />
                  Agent Working
                </Badge>
              )}
            </div>
            {pipelineEvent && (
              <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
                <GitCommit className="size-4 shrink-0 text-accent" />
                <span>{pipelineEvent.message}</span>
              </p>
            )}
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {stats.map((s) => (
            <div
              key={s.label}
              className="rounded-lg border border-border bg-card px-3.5 py-3"
            >
              <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
                <s.icon className={`size-3.5 ${s.tone}`} />
                {s.label}
              </div>
              <div className="mt-1.5 truncate font-mono text-sm font-medium text-foreground">
                {s.value}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
