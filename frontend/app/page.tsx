"use client"

import { useEffect, useState } from "react"
import { TopBar } from "@/components/top-bar"
import { PipelineHeader } from "@/components/pipeline-header"
import { AgentTimeline } from "@/components/agent-timeline"
import { LogPanel } from "@/components/log-panel"
import { TerminalUI } from "@/components/terminal-ui"
import { MergeRequestPanel } from "@/components/merge-request-panel"
import { getActiveSession } from "@/lib/api"
import { useAxolotlSocket, type WSEvent } from "@/lib/use-websocket"
import type { AgentStage, StageState, LogLine } from "@/lib/axolotl-data"

/** Map backend event_type → agent stage key */
const EVENT_TO_STAGE: Record<string, string> = {
  pipeline_failed: "detect",
  fetching_logs: "fetch-logs",
  analyzing: "analyze",
  generating_fix: "generate-fix",
  creating_branch: "branch",
  committing: "commit",
  creating_mr: "merge-request",
  waiting_approval: "approval",
}

/** All stage definitions in order */
const STAGE_DEFS: { key: string; label: string }[] = [
  { key: "detect", label: "Detect Failure" },
  { key: "fetch-logs", label: "Fetch Pipeline Logs" },
  { key: "analyze", label: "Analyze Root Cause" },
  { key: "generate-fix", label: "Generate Fix" },
  { key: "branch", label: "Create Branch" },
  { key: "commit", label: "Commit Fix" },
  { key: "merge-request", label: "Raise Merge Request" },
  { key: "approval", label: "Human Approval" },
]

function buildStagesFromEvents(events: Array<{ event_type: string; message: string }>): AgentStage[] {
  const completedKeys = new Set<string>()
  let activeKey: string | null = null

  for (const ev of events) {
    const stageKey = EVENT_TO_STAGE[ev.event_type]
    if (stageKey) {
      if (activeKey && activeKey !== stageKey) {
        completedKeys.add(activeKey)
      }
      activeKey = stageKey
    }
  }

  const eventTypes = new Set(events.map((e) => e.event_type))
  if (eventTypes.has("fix_succeeded") || eventTypes.has("waiting_approval")) {
    if (activeKey) completedKeys.add(activeKey)
    activeKey = null
  }

  return STAGE_DEFS.map((def) => {
    let state: StageState = "pending"
    if (completedKeys.has(def.key)) state = "done"
    else if (def.key === activeKey) state = "active"

    const matchingEvent = events.find((e) => EVENT_TO_STAGE[e.event_type] === def.key)
    return {
      key: def.key as AgentStage["key"],
      label: def.label,
      description: matchingEvent?.message || "",
      state,
    }
  })
}

function wsEventToLogLine(ev: WSEvent): LogLine {
  const ts = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString("en-GB", { hour12: false }).slice(0, 8) : ""
  const levelMap: Record<string, LogLine["level"]> = {
    pipeline_failed: "error",
    fix_failed: "error",
    fetching_logs: "info",
    analyzing: "info",
    generating_fix: "info",
    creating_branch: "info",
    committing: "success",
    creating_mr: "success",
    waiting_approval: "warn",
    fix_succeeded: "success",
  }
  return {
    ts,
    level: levelMap[ev.event_type] || "info",
    source: "axolotl",
    message: ev.message,
  }
}

export default function Page() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [initialEvents, setInitialEvents] = useState<Array<{ event_type: string; message: string }>>([])
  const [isLoading, setIsLoading] = useState(true)

  // ALWAYS connect to the "dashboard" WebSocket channel
  // This receives ALL events from every pipeline session
  const { events: wsEvents, isConnected } = useAxolotlSocket("dashboard", true)

  // Load any existing active session on mount
  useEffect(() => {
    async function load() {
      try {
        const data = await getActiveSession()
        if (data.active_session) {
          setSessionId(data.active_session.session_id)
          setInitialEvents(
            data.active_session.events.map((e) => ({
              event_type: e.event_type,
              message: e.message,
            }))
          )
        }
      } catch (e) {
        console.error("Failed to load active session:", e)
      } finally {
        setIsLoading(false)
      }
    }
    load()
  }, [])

  // When a new pipeline_failed event arrives via WS, auto-activate the session
  useEffect(() => {
    if (wsEvents.length === 0) return
    const latestStart = wsEvents.find((e) => e.event_type === "pipeline_failed")
    if (latestStart && !sessionId) {
      const sid = (latestStart as any).session_id || "live"
      setSessionId(sid)
    }
  }, [wsEvents, sessionId])

  // Merge initial events + WebSocket events
  const allEventData = [
    ...initialEvents,
    ...wsEvents.map((e) => ({ event_type: e.event_type, message: e.message })),
  ]

  const hasEvents = allEventData.length > 0
  const stages = buildStagesFromEvents(allEventData)
  const completedCount = stages.filter((s) => s.state === "done").length
  const agentLogs: LogLine[] = wsEvents.map(wsEventToLogLine)

  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <PipelineHeader
        sessionId={sessionId}
        events={allEventData}
        isConnected={isConnected}
      />

      <main className="mx-auto w-full max-w-[1600px] px-4 py-5 md:px-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="flex flex-col items-center gap-4">
              <div className="size-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
              <p className="text-sm text-muted-foreground animate-pulse">Loading dashboard...</p>
            </div>
          </div>
        ) : !hasEvents ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="flex size-16 items-center justify-center rounded-full border border-border bg-secondary mb-4">
              <span className="text-2xl">🦎</span>
            </div>
            <h2 className="text-lg font-semibold text-foreground">Waiting for pipeline events</h2>
            <p className="mt-2 max-w-md text-sm text-muted-foreground">
              Axolotl is watching your pipelines. When a failure is detected, the agent workflow will appear here in real-time.
            </p>
            <div className="mt-4 flex items-center gap-2 rounded-md border border-chart-3/30 bg-chart-3/10 px-3 py-2 text-xs text-chart-3">
              {isConnected ? (
                <>
                  <span className="size-1.5 animate-pulse rounded-full bg-chart-3" />
                  WebSocket connected · Listening for events
                </>
              ) : (
                <>
                  <span className="size-1.5 rounded-full bg-chart-4" />
                  Connecting to WebSocket...
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[340px_1fr]">
            {/* left rail: agent workflow */}
            <aside className="xl:sticky xl:top-[3.75rem] xl:self-start">
              <AgentTimeline stages={stages} completedCount={completedCount} />
            </aside>

            {/* right: panels */}
            <div className="flex flex-col gap-4">
              {/* terminal + logs row */}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="h-[340px]">
                  <TerminalUI wsEvents={wsEvents} isConnected={isConnected} />
                </div>
                <div className="h-[340px]">
                  <LogPanel
                    title="Agent Logs"
                    subtitle={`session: ${sessionId || "dashboard"}`}
                    logs={agentLogs}
                    accent="agent"
                  />
                </div>
              </div>

              {/* merge request */}
              <MergeRequestPanel />
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-border px-4 py-4 md:px-6">
        <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-2 font-mono text-xs text-muted-foreground">
          <span>axolotl agent runtime v1.4.2</span>
          <span>
            {isConnected ? (
              <span className="flex items-center gap-1.5">
                <span className="size-1.5 animate-pulse rounded-full bg-chart-3" />
                WebSocket connected
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <span className="size-1.5 rounded-full bg-muted-foreground" />
                WebSocket disconnected
              </span>
            )}
          </span>
        </div>
      </footer>
    </div>
  )
}
