"use client"

import { useState } from "react"
import type { APIMergeRequest } from "@/lib/api"
import { AxolotlMark } from "@/components/axolotl-mark"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { GitMerge, GitBranch, ArrowRight, FileDiff, CheckCircle2, XCircle, Search } from "lucide-react"

type StatusFilter = "all" | "open" | "merged" | "closed"

const statusBadge: Record<string, { label: string; cls: string }> = {
  open: { label: "Open", cls: "border-chart-3/30 bg-chart-3/15 text-chart-3" },
  merged: { label: "Merged", cls: "border-primary/30 bg-primary/15 text-primary" },
  closed: { label: "Closed", cls: "border-destructive/30 bg-destructive/15 text-destructive" },
}

interface MergeRequestListProps {
  mergeRequests: APIMergeRequest[]
}

export function MergeRequestList({ mergeRequests }: MergeRequestListProps) {
  const [filter, setFilter] = useState<StatusFilter>("all")
  const rows = mergeRequests.filter((m) => filter === "all" || m.status === filter)

  const tabs: { label: string; value: StatusFilter; count: number }[] = [
    { label: "All", value: "all", count: mergeRequests.length },
    { label: "Open", value: "open", count: mergeRequests.filter((m) => m.status === "open").length },
    { label: "Merged", value: "merged", count: mergeRequests.filter((m) => m.status === "merged").length },
    { label: "Closed", value: "closed", count: mergeRequests.filter((m) => m.status === "closed").length },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {tabs.map((t) => (
          <button
            key={t.value}
            onClick={() => setFilter(t.value)}
            className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === t.value
                ? "border-primary/40 bg-primary/15 text-primary"
                : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground"
            }`}
          >
            {t.label}
            <span className="font-mono text-[10px] opacity-70">{t.count}</span>
          </button>
        ))}
        <div className="ml-auto hidden items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-muted-foreground sm:flex">
          <Search className="size-3.5" />
          <span className="font-mono">filter by branch…</span>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="flex items-center justify-center rounded-lg border border-border bg-card px-4 py-12 text-sm text-muted-foreground">
          No merge requests found.
        </div>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((mr) => {
            const sb = statusBadge[mr.status] || statusBadge.open
            return (
              <li
                key={mr.iid}
                className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/30 md:p-5"
              >
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <GitMerge className="size-4 text-accent" />
                      <span className="font-mono text-sm text-muted-foreground">{mr.iid}</span>
                      <Badge className={`hover:bg-transparent ${sb.cls}`}>{sb.label}</Badge>
                      <Badge variant="outline" className="font-mono text-[11px] text-muted-foreground">
                        {mr.project}
                      </Badge>
                    </div>
                    <h3 className="mt-2 text-pretty font-mono text-sm font-semibold text-foreground">
                      {mr.title}
                    </h3>
                    {mr.author_is_agent && mr.root_cause !== "—" && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        <span className="text-accent">root cause:</span> {mr.root_cause}
                      </p>
                    )}

                    <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-[11px]">
                      <span className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-primary">
                        <GitBranch className="size-3" />
                        {mr.source_branch}
                      </span>
                      <ArrowRight className="size-3 text-muted-foreground" />
                      <span className="flex items-center gap-1.5 rounded-md border border-border bg-secondary px-2 py-1 text-foreground">
                        <GitBranch className="size-3" />
                        {mr.target_branch}
                      </span>
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-col gap-2 lg:items-end">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {mr.author_is_agent ? (
                        <AxolotlMark className="size-5" />
                      ) : (
                        <Avatar className="size-5">
                          <AvatarFallback className="bg-secondary text-[9px] text-foreground">
                            {mr.author.slice(0, 2).toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                      )}
                      <span className="text-foreground">{mr.author}</span>
                    </div>
                    <div className="flex items-center gap-3 font-mono text-xs">
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <FileDiff className="size-3.5" />
                        {mr.files_changed}
                      </span>
                      <span className="text-chart-3">+{mr.additions}</span>
                      <span className="text-destructive">-{mr.deletions}</span>
                      {mr.pipeline_passing ? (
                        <span className="flex items-center gap-1 text-chart-3">
                          <CheckCircle2 className="size-3.5" /> passing
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-chart-4">
                          <XCircle className="size-3.5" /> running
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
