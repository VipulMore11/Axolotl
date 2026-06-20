"use client"

import { useEffect, useState } from "react"
import { getMergeRequests, approveMergeRequest, rejectMergeRequest, mergeMergeRequest, type APIMergeRequest } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { AxolotlMark } from "@/components/axolotl-mark"
import { Check, X, GitMerge, GitBranch, FileDiff, CheckCircle2, ArrowRight, Loader2 } from "lucide-react"

export function MergeRequestPanel() {
  const [mr, setMr] = useState<APIMergeRequest | null>(null)
  const [decision, setDecision] = useState<"pending" | "approved" | "rejected">("pending")
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const data = await getMergeRequests("opened")
        // Find the first agent-raised open MR
        const agentMr = data.merge_requests.find((m) => m.author_is_agent && m.status === "open")
        if (agentMr) {
          setMr(agentMr)
        } else if (data.merge_requests.length > 0) {
          setMr(data.merge_requests[0])
        }
      } catch (e) {
        console.error("Failed to load MRs:", e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-border bg-card p-8">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading merge requests...
        </div>
      </div>
    )
  }

  if (!mr) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-card p-8 text-center">
        <GitMerge className="size-8 text-muted-foreground/40 mb-2" />
        <p className="text-sm text-muted-foreground">No open merge requests from the agent.</p>
      </div>
    )
  }

  async function handleApprove() {
    if (!mr) return
    setActing(true)
    try {
      await mergeMergeRequest(mr.project_id, mr.raw_iid)
      setDecision("approved")
      if (typeof pendo !== "undefined") {
        pendo.track("merge_request_approved", {
          project_id: mr.project_id,
          mr_iid: String(mr.raw_iid),
          mr_title: mr.title,
          source_branch: mr.source_branch,
          target_branch: mr.target_branch,
          files_changed: mr.files_changed,
          additions: mr.additions,
          deletions: mr.deletions,
          author_is_agent: mr.author_is_agent,
          pipeline_passing: mr.pipeline_passing,
        })
      }
    } catch (e) {
      // Try approve if merge fails
      try {
        await approveMergeRequest(mr.project_id, mr.raw_iid)
        setDecision("approved")
        if (typeof pendo !== "undefined") {
          pendo.track("merge_request_approved", {
            project_id: mr.project_id,
            mr_iid: String(mr.raw_iid),
            mr_title: mr.title,
            source_branch: mr.source_branch,
            target_branch: mr.target_branch,
            files_changed: mr.files_changed,
            additions: mr.additions,
            deletions: mr.deletions,
            author_is_agent: mr.author_is_agent,
            pipeline_passing: mr.pipeline_passing,
          })
        }
      } catch {
        console.error("Failed to approve:", e)
      }
    } finally {
      setActing(false)
    }
  }

  async function handleReject() {
    if (!mr) return
    setActing(true)
    try {
      await rejectMergeRequest(mr.project_id, mr.raw_iid)
      setDecision("rejected")
      if (typeof pendo !== "undefined") {
        pendo.track("merge_request_rejected", {
          project_id: mr.project_id,
          mr_iid: String(mr.raw_iid),
          mr_title: mr.title,
          source_branch: mr.source_branch,
          target_branch: mr.target_branch,
          files_changed: mr.files_changed,
          additions: mr.additions,
          deletions: mr.deletions,
          author_is_agent: mr.author_is_agent,
        })
      }
    } catch (e) {
      console.error("Failed to reject:", e)
    } finally {
      setActing(false)
    }
  }

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
                  {mr.status === "open" ? "Open" : mr.status === "merged" ? "Merged" : "Closed"}
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
            {mr.source_branch}
          </span>
          <ArrowRight className="size-3.5 text-muted-foreground" />
          <span className="flex items-center gap-1.5 rounded-md border border-border bg-secondary px-2 py-1 text-foreground">
            <GitBranch className="size-3.5" />
            {mr.target_branch}
          </span>
        </div>

        {/* meta row */}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            {mr.author_is_agent ? <AxolotlMark className="size-4" /> : null}
            opened by <span className="text-foreground">{mr.author}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <FileDiff className="size-3.5" />
            {mr.files_changed} file{mr.files_changed !== 1 ? "s" : ""}
          </span>
          <span className="font-mono text-chart-3">+{mr.additions}</span>
          <span className="font-mono text-destructive">-{mr.deletions}</span>
          {mr.pipeline_passing && (
            <span className="flex items-center gap-1.5 text-chart-3">
              <CheckCircle2 className="size-3.5" />
              checks passing
            </span>
          )}
        </div>
      </div>

      {/* description */}
      {mr.description && (
        <div className="border-b border-border bg-secondary/30 px-4 py-3 md:px-5">
          <p className="text-sm leading-relaxed text-muted-foreground line-clamp-3">{mr.description}</p>
        </div>
      )}

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
                Review and approve to merge
              </p>
            </div>
          </div>

          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={decision !== "pending" || acting}
              onClick={handleReject}
              className="border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
            >
              {acting ? <Loader2 className="size-4 animate-spin" /> : <X className="size-4" />}
              Reject
            </Button>
            <Button
              size="sm"
              disabled={decision !== "pending" || acting}
              onClick={handleApprove}
              className="bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {acting ? <Loader2 className="size-4 animate-spin" /> : <GitMerge className="size-4" />}
              Approve &amp; Merge
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
