"use client"

import { useState } from "react"
import Link from "next/link"
import { pipelines, type PipelineStatus } from "@/lib/axolotl-data"
import { StatusBadge } from "@/components/status-badge"
import { AxolotlMark } from "@/components/axolotl-mark"
import { GitCommit, GitBranch, Clock } from "lucide-react"

const filters: { label: string; value: PipelineStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Failed", value: "failed" },
  { label: "Agent Fixing", value: "fixing" },
  { label: "Awaiting Approval", value: "awaiting-approval" },
  { label: "Running", value: "running" },
  { label: "Passed", value: "passed" },
]

export function PipelinesTable() {
  const [filter, setFilter] = useState<PipelineStatus | "all">("all")
  const rows = pipelines.filter((p) => filter === "all" || p.status === filter)

  return (
    <div className="flex flex-col gap-4">
      {/* filter bar */}
      <div className="flex flex-wrap items-center gap-1.5">
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === f.value
                ? "border-primary/40 bg-primary/15 text-primary"
                : "border-border bg-card text-muted-foreground hover:border-border hover:bg-secondary hover:text-foreground"
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {rows.length} pipeline{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      {/* table */}
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="hidden grid-cols-[110px_1fr_160px_120px_110px] gap-4 border-b border-border bg-secondary/40 px-4 py-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground md:grid">
          <span>Pipeline</span>
          <span>Commit</span>
          <span>Branch</span>
          <span>Status</span>
          <span className="text-right">Duration</span>
        </div>
        <ul>
          {rows.map((p) => (
            <li key={p.id}>
              <Link
                href="/"
                className="grid grid-cols-1 gap-2 border-b border-border/60 px-4 py-3.5 transition-colors last:border-0 hover:bg-secondary/40 md:grid-cols-[110px_1fr_160px_120px_110px] md:items-center md:gap-4"
              >
                <div className="flex items-center gap-2 font-mono text-sm text-foreground">
                  {p.agentEngaged && <AxolotlMark className="size-4 shrink-0" />}
                  {p.id}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-sm text-foreground">
                    <GitCommit className="size-3.5 shrink-0 text-accent" />
                    <span className="truncate">{p.commitMessage}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                    <span className="text-accent/70">{p.commit}</span>
                    <span>by {p.author}</span>
                    <span className="text-muted-foreground/40">·</span>
                    <span>{p.project}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                  <GitBranch className="size-3.5 shrink-0" />
                  <span className="truncate">{p.ref}</span>
                </div>
                <div>
                  <StatusBadge status={p.status} />
                </div>
                <div className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground md:justify-end">
                  <Clock className="size-3.5 md:hidden" />
                  {p.duration}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
