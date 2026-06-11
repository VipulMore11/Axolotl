"use client"

import { useEffect, useRef, useState } from "react"
import { Terminal as TerminalIcon } from "lucide-react"

interface Line {
  type: "prompt" | "out" | "ok" | "err" | "warn" | "muted"
  text: string
}

const bootSequence: Line[] = [
  { type: "muted", text: "axolotl agent runtime v1.4.2 — connected to gitlab.platform.io" },
  { type: "prompt", text: "axolotl watch --project platform-api --branch main" },
  { type: "out", text: "▸ subscribed to pipeline webhooks (push, merge_request)" },
  { type: "warn", text: "✖ pipeline #48291 reported status=failed" },
  { type: "out", text: "▸ fetching trace for job test:integration ..." },
  { type: "ok", text: "✓ 4,812 log lines retrieved (142 KB)" },
  { type: "out", text: "▸ analyzing root cause with gemini-2.5-pro ..." },
  { type: "ok", text: "✓ root cause: cookies() called synchronously in edge runtime" },
  { type: "out", text: "▸ generating patch for middleware/auth.ts ..." },
  { type: "ok", text: "✓ branch axolotl/fix-edge-auth-48291 created" },
  { type: "ok", text: "✓ committed b91e7d2 · merge request !1043 opened" },
  { type: "warn", text: "⏸ human-in-the-loop: awaiting reviewer approval" },
]

const lineColor: Record<Line["type"], string> = {
  prompt: "text-foreground",
  out: "text-muted-foreground",
  ok: "text-chart-3",
  err: "text-destructive",
  warn: "text-chart-4",
  muted: "text-muted-foreground/60",
}

export function TerminalUI() {
  const [visible, setVisible] = useState<Line[]>([])
  const [input, setInput] = useState("")
  const [history, setHistory] = useState<Line[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let i = 0
    const interval = setInterval(() => {
      if (i >= bootSequence.length) {
        clearInterval(interval)
        return
      }
      const next = bootSequence[i]
      i++
      setVisible((prev) => [...prev, next])
    }, 450)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [visible, history])

  function runCommand(cmd: string) {
    const trimmed = cmd.trim()
    if (!trimmed) return
    const responses: Line[] = [{ type: "prompt", text: trimmed }]
    switch (trimmed) {
      case "help":
        responses.push(
          { type: "out", text: "available: status · logs · approve · reject · diff · clear" },
        )
        break
      case "status":
        responses.push(
          { type: "ok", text: "pipeline #48291 · awaiting-approval · MR !1043 open" },
        )
        break
      case "approve":
        responses.push(
          { type: "ok", text: "✓ approval recorded — merging !1043 into main" },
          { type: "muted", text: "  triggering deploy pipeline ..." },
        )
        break
      case "reject":
        responses.push({ type: "err", text: "✖ MR !1043 rejected — agent will re-analyze" })
        break
      case "diff":
        responses.push(
          { type: "muted", text: "middleware/auth.ts (+6 / -3)" },
          { type: "err", text: "- const store = cookies()" },
          { type: "ok", text: "+ const store = await cookies()" },
        )
        break
      case "logs":
        responses.push({ type: "muted", text: "see Error / Agent log panels →" })
        break
      case "clear":
        setHistory([])
        setVisible([])
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
          <span className="font-mono text-sm text-foreground">axolotl@platform-api</span>
        </div>
        <div className="flex gap-1.5">
          <span className="size-2.5 rounded-full bg-chart-4/60" />
          <span className="size-2.5 rounded-full bg-chart-3/60" />
          <span className="size-2.5 rounded-full bg-destructive/60" />
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto px-4 py-3 font-mono text-xs leading-relaxed">
        {[...visible, ...history].filter(Boolean).map((line, i) => (
          <div key={i} className="flex gap-2">
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
          placeholder="type 'help' — try status, approve, diff"
          spellCheck={false}
          autoComplete="off"
          className="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
          aria-label="Terminal command input"
        />
      </form>
    </div>
  )
}
