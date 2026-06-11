import type { PipelineStatus } from "@/lib/axolotl-data"
import { Badge } from "@/components/ui/badge"

const map: Record<PipelineStatus, { label: string; cls: string; pulse?: boolean }> = {
  running: { label: "Running", cls: "border-accent/30 bg-accent/15 text-accent", pulse: true },
  failed: { label: "Failed", cls: "border-destructive/30 bg-destructive/15 text-destructive" },
  fixing: { label: "Agent Fixing", cls: "border-chart-4/30 bg-chart-4/15 text-chart-4", pulse: true },
  "awaiting-approval": {
    label: "Awaiting Approval",
    cls: "border-primary/30 bg-primary/15 text-primary",
    pulse: true,
  },
  passed: { label: "Passed", cls: "border-chart-3/30 bg-chart-3/15 text-chart-3" },
}

export function StatusBadge({ status }: { status: PipelineStatus }) {
  const s = map[status]
  return (
    <Badge className={`gap-1.5 font-medium hover:bg-transparent ${s.cls}`}>
      {s.pulse && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {s.label}
    </Badge>
  )
}
