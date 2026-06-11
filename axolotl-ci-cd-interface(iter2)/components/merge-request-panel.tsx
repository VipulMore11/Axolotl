"use client"

import { useState } from "react"
import { mergeRequest, type DiffLine } from "@/lib/axolotl-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { AxolotlMark } from "@/components/axolotl-mark"
import { Check, X, GitMerge, GitBranch, FileDiff, CheckCircle2, ArrowRight } from "lucide-react"

function DiffRow({ line }: { line: DiffLine }) {
  if (line.type === "meta") {
    return (
      <tr className="bg-accent/5">
        <td colSpan={3} className="px-3 py-0.5 font-mono text-[11px] text-accent/80">
          {line.text}
        </td>
      </tr>
    )
  }
  const bg =
    line.type === "add" ? "bg-chart-3/10" : line.type === "remove" ? "bg-destructive/10" : ""
  const sign = line.type === "add" ? "+" : line.type === "remove" ? "-" : " "
  const textColor =
    line.type === "add"
      ? "text-chart-3"
      : line.type === "remove"
        ? "text-destructive"
        : "text-muted-foreground"
  return (
    <tr className={`group ${bg}`}>
      <td className="w-10 select-none border-r border-border/40 px-2 py-0.5 text-right font-mono text-[11px] text-muted-foreground/40 tabular-nums">
        {line.oldNo ?? ""}
      </td>
      <td className="w-10 select-none border-r border-border/40 px-2 py-0.5 text-right font-mono text-[11px] text-muted-foreground/40 tabular-nums">
        {line.newNo ?? ""}
      </td>
      <td className={`whitespace-pre px-3 py-0.5 font-mono text-xs ${textColor}`}>
        <span className="mr-2 select-none opacity-60">{sign}</span>
        {line.text || " "}
      </td>
    </tr>
  )
}

export function MergeRequestPanel() {
  const [decision, setDecision] = useState<"pending" | "approved" | "rejected">("pending")
  const mr = mergeRequest

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      {/* header */}
      <div className="border-b border-border px-4 py-4 md:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <GitMerge className="size-4 text-accent" />
              <span className="font-mono text-sm text-muted-foreground">{mr.iid}</span>
              {decision === "pending" && (
                <Badge className="border-chart-3/30 bg-chart-3/15 text-chart-3 hover:bg-chart-3/15">
                  Open
                </Badge>
              )}
              {decision === "approved" && (
                <Badge className="border-primary/30 bg-primary/15 text-primary hover:bg-primary/15">
                  Merged
                </Badge>
              )}
              {decision === "rejected" && (
                <Badge className="border-destructive/30 bg-destructive/15 text-destructive hover:bg-destructive/15">
                  Closed
                </Badge>
              )}
            </div>
            <h2 className="mt-2 text-pretty font-mono text-base font-semibold text-foreground">
              {mr.title}
            </h2>
          </div>
        </div>

        {/* branch flow */}
        <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-xs">
          <span className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-primary">
            <GitBranch className="size-3.5" />
            {mr.sourceBranch}
          </span>
          <ArrowRight className="size-3.5 text-muted-foreground" />
          <span className="flex items-center gap-1.5 rounded-md border border-border bg-secondary px-2 py-1 text-foreground">
            <GitBranch className="size-3.5" />
            {mr.targetBranch}
          </span>
        </div>

        {/* meta row */}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <AxolotlMark className="size-4" />
            opened by <span className="text-foreground">{mr.author}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <FileDiff className="size-3.5" />
            {mr.filesChanged} file
          </span>
          <span className="font-mono text-chart-3">+{mr.additions}</span>
          <span className="font-mono text-destructive">-{mr.deletions}</span>
          {mr.pipelinePassing && (
            <span className="flex items-center gap-1.5 text-chart-3">
              <CheckCircle2 className="size-3.5" />
              checks passing
            </span>
          )}
        </div>
      </div>

      {/* description */}
      <div className="border-b border-border bg-secondary/30 px-4 py-3 md:px-5">
        <p className="text-sm leading-relaxed text-muted-foreground">{mr.description}</p>
      </div>

      {/* diff */}
      <div className="border-b border-border">
        <div className="flex items-center gap-2 border-b border-border bg-secondary/40 px-4 py-2 md:px-5">
          <FileDiff className="size-3.5 text-accent" />
          <span className="font-mono text-xs text-foreground">{mr.diffFile}</span>
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">
            <span className="text-chart-3">+{mr.additions}</span>{" "}
            <span className="text-destructive">-{mr.deletions}</span>
          </span>
        </div>
        <div className="overflow-x-auto bg-[oklch(0.13_0.006_285)]">
          <table className="w-full border-collapse">
            <tbody>
              {mr.diff.map((line, i) => (
                <DiffRow key={i} line={line} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* human-in-the-loop approval gate */}
      <div className="px-4 py-4 md:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2.5">
            <span
              className={`flex size-8 items-center justify-center rounded-full ${
                decision === "approved"
                  ? "bg-chart-3/15 text-chart-3"
                  : decision === "rejected"
                    ? "bg-destructive/15 text-destructive"
                    : "bg-primary/15 text-primary"
              }`}
            >
              {decision === "approved" ? (
                <Check className="size-4" />
              ) : decision === "rejected" ? (
                <X className="size-4" />
              ) : (
                <span className="size-2 animate-pulse rounded-full bg-primary" />
              )}
            </span>
            <div className="leading-tight">
              <p className="text-sm font-medium text-foreground">
                {decision === "pending"
                  ? "Human-in-the-loop gate"
                  : decision === "approved"
                    ? "Approved — deploying"
                    : "Rejected — re-analyzing"}
              </p>
              <p className="text-xs text-muted-foreground">
                {mr.approvalsGiven} of {mr.approvalsRequired} required approval
              </p>
            </div>
          </div>

          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={decision !== "pending"}
              onClick={() => setDecision("rejected")}
              className="border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
            >
              <X className="size-4" />
              Reject
            </Button>
            <Button
              size="sm"
              disabled={decision !== "pending"}
              onClick={() => setDecision("approved")}
              className="bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <GitMerge className="size-4" />
              Approve &amp; Merge
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
