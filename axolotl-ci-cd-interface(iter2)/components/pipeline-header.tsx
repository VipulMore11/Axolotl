import { Badge } from "@/components/ui/badge"
import { pipeline } from "@/lib/axolotl-data"
import { CircleDot, Clock, GitCommit, Bot, ShieldCheck } from "lucide-react"

const stats = [
  { label: "Failed Job", value: "test:integration", icon: CircleDot, tone: "text-destructive" },
  { label: "Detected → MR", value: "21.4s", icon: Clock, tone: "text-accent" },
  { label: "Model", value: "gemini-2.5-pro", icon: Bot, tone: "text-foreground" },
  { label: "Confidence", value: "94%", icon: ShieldCheck, tone: "text-chart-3" },
]

export function PipelineHeader() {
  return (
    <section className="border-b border-border bg-card/40">
      <div className="px-4 py-5 md:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-mono text-lg font-semibold text-foreground">
                Pipeline {pipeline.id}
              </h1>
              <Badge className="gap-1.5 border-primary/30 bg-primary/15 text-primary hover:bg-primary/15">
                <span className="size-1.5 animate-pulse rounded-full bg-primary" />
                Awaiting Approval
              </Badge>
              <Badge variant="outline" className="font-mono text-xs text-muted-foreground">
                trigger: {pipeline.trigger}
              </Badge>
            </div>
            <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
              <GitCommit className="size-4 shrink-0 text-accent" />
              <span className="font-mono text-foreground">{pipeline.commit}</span>
              <span className="truncate">{pipeline.commitMessage}</span>
              <span className="text-muted-foreground/50">·</span>
              <span>by {pipeline.author}</span>
              <span className="text-muted-foreground/50">·</span>
              <span className="font-mono">{pipeline.startedAt}</span>
            </p>
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
