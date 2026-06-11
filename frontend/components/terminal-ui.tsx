"use client"

import { useEffect, useRef, useState } from "react"
import { Terminal as TerminalIcon } from "lucide-react"
import type { WSEvent } from "@/lib/use-websocket"

interface Line {
  type: "prompt" | "out" | "ok" | "err" | "warn" | "muted"
  text: string
}

const lineColor: Record<Line["type"], string> = {
  prompt: "text-foreground",
  out: "text-muted-foreground",
  ok: "text-chart-3",
  err: "text-destructive",
  warn: "text-chart-4",
  muted: "text-muted-foreground/60",
}

const eventTypeToLine: Record<string, Line["type"]> = {
  pipeline_failed: "err",
  fetching_logs: "out",
  analyzing: "out",
  generating_fix: "out",
  creating_branch: "out",
  committing: "ok",
  creating_mr: "ok",
  waiting_approval: "warn",
  fix_succeeded: "ok",
  fix_failed: "err",
}

interface TerminalUIProps {
  wsEvents?: WSEvent[]
  isConnected?: boolean
}

export function TerminalUI({ wsEvents = [], isConnected = false }: TerminalUIProps) {
  const [input, setInput] = useState("")
  const [history, setHistory] = useState<Line[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  // Convert WS events to terminal lines
  const wsLines: Line[] = wsEvents.map((ev) => ({
    type: eventTypeToLine[ev.event_type] || "out",
    text: ev.message,
  }))

  // Boot line
  const bootLine: Line = {
    type: "muted",
    text: `axolotl agent runtime v1.4.2 — ${isConnected ? "connected" : "disconnected"}`,
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [wsLines.length, history])

  function runCommand(cmd: string) {
    const trimmed = cmd.trim()
    if (!trimmed) return
    const responses: Line[] = [{ type: "prompt", text: trimmed }]
    switch (trimmed) {
      case "help":
        responses.push(
          { type: "out", text: "available: status · logs · clear" },
        )
        break
      case "status":
        responses.push(
          { type: isConnected ? "ok" : "warn", text: `WebSocket: ${isConnected ? "connected" : "disconnected"} · ${wsEvents.length} events received` },
        )
        break
      case "logs":
        responses.push({ type: "muted", text: "see Agent log panel →" })
        break
      case "clear":
        setHistory([])
        return
      default:
        responses.push({ type: "err", text: `command not found: ${trimmed} (try 'help')` })
    }
    setHistory((prev) => [...prev, ...responses])
  }

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-border bg-[oklch(0.12_0.006_285)]">
      <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <TerminalIcon className="size-4 text-accent" />
          <span className="font-mono text-sm text-foreground">axolotl</span>
          {isConnected && (
            <span className="size-1.5 animate-pulse rounded-full bg-chart-3" />
          )}
        </div>
        <div className="flex gap-1.5">
          <span className="size-2.5 rounded-full bg-chart-4/60" />
          <span className="size-2.5 rounded-full bg-chart-3/60" />
          <span className="size-2.5 rounded-full bg-destructive/60" />
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto px-4 py-3 font-mono text-xs leading-relaxed">
        {/* Boot line */}
        <div className="flex gap-2">
          <span className={`whitespace-pre-wrap ${lineColor[bootLine.type]}`}>{bootLine.text}</span>
        </div>
        {/* WS events */}
        {wsLines.map((line, i) => (
          <div key={`ws-${i}`} className="flex gap-2">
            <span className="shrink-0 text-accent">▸</span>
            <span className={`whitespace-pre-wrap ${lineColor[line.type]}`}>{line.text}</span>
          </div>
        ))}
        {/* User command history */}
        {history.filter(Boolean).map((line, i) => (
          <div key={`h-${i}`} className="flex gap-2">
            {line.type === "prompt" && <span className="shrink-0 text-primary">$</span>}
            <span className={`whitespace-pre-wrap ${lineColor[line.type]}`}>{line.text}</span>
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          runCommand(input)
          setInput("")
        }}
        className="flex items-center gap-2 border-t border-border bg-card/60 px-4 py-2.5 font-mono text-xs"
      >
        <span className="text-primary">$</span>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="type 'help' — try status, logs, clear"
          spellCheck={false}
          autoComplete="off"
          className="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
          aria-label="Terminal command input"
        />
      </form>
    </div>
  )
}
