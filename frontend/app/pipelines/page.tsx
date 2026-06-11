import { TopBar } from "@/components/top-bar"
import { PageHeader } from "@/components/page-header"
import { PipelinesTable } from "@/components/pipelines-table"
import { pipelines } from "@/lib/axolotl-data"

export default function PipelinesPage() {
  const failing = pipelines.filter((p) => p.status === "failed" || p.status === "fixing").length
  const engaged = pipelines.filter((p) => p.agentEngaged).length

  const stats = [
    { label: "Monitored", value: pipelines.length },
    { label: "Agent Engaged", value: engaged },
    { label: "Failing Now", value: failing },
    { label: "Projects", value: 3 },
  ]

  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <PageHeader
        title="Pipelines"
        description="Every GitLab CI/CD pipeline Axolotl watches. Failing runs are picked up automatically and routed through the agent repair workflow."
        meta={
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {stats.map((s) => (
              <div key={s.label} className="rounded-lg border border-border bg-card px-4 py-3">
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                  {s.label}
                </div>
                <div className="mt-1 font-mono text-2xl font-semibold text-foreground">
                  {s.value}
                </div>
              </div>
            ))}
          </div>
        }
      />
      <main className="mx-auto w-full max-w-[1600px] px-4 py-6 md:px-6">
        <PipelinesTable />
      </main>
    </div>
  )
}
