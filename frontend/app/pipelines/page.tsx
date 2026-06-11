"use client"

import { useEffect, useState } from "react"
import { TopBar } from "@/components/top-bar"
import { PageHeader } from "@/components/page-header"
import { PipelinesTable } from "@/components/pipelines-table"
import { getPipelines, type APIPipeline } from "@/lib/api"
import { Loader2 } from "lucide-react"

export default function PipelinesPage() {
  const [pipelines, setPipelines] = useState<APIPipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const data = await getPipelines()
        setPipelines(data.pipelines)
      } catch (e) {
        console.error("Failed to load pipelines:", e)
        setError("Failed to load pipelines. Check that you have watched projects in Settings.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const failing = pipelines.filter((p) => p.status === "failed" || p.status === "fixing").length
  const engaged = pipelines.filter((p) => p.agent_engaged).length
  const projectSet = new Set(pipelines.map((p) => p.project_name))

  const stats = [
    { label: "Monitored", value: pipelines.length },
    { label: "Agent Engaged", value: engaged },
    { label: "Failing Now", value: failing },
    { label: "Projects", value: projectSet.size },
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
                  {loading ? "—" : s.value}
                </div>
              </div>
            ))}
          </div>
        }
      />
      <main className="mx-auto w-full max-w-[1600px] px-4 py-6 md:px-6">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading pipelines...
            </div>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <p className="text-sm text-muted-foreground">{error}</p>
          </div>
        ) : (
          <PipelinesTable pipelines={pipelines} />
        )}
      </main>
    </div>
  )
}
