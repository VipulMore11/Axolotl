import { TopBar } from "@/components/top-bar"
import { PipelineHeader } from "@/components/pipeline-header"
import { AgentTimeline } from "@/components/agent-timeline"
import { LogPanel } from "@/components/log-panel"
import { TerminalUI } from "@/components/terminal-ui"
import { MergeRequestPanel } from "@/components/merge-request-panel"
import { errorLogs, agentLogs } from "@/lib/axolotl-data"

export default function Page() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <PipelineHeader />

      <main className="mx-auto w-full max-w-[1600px] px-4 py-5 md:px-6">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[340px_1fr]">
          {/* left rail: agent workflow */}
          <aside className="xl:sticky xl:top-[3.75rem] xl:self-start">
            <AgentTimeline />
          </aside>

          {/* right: panels */}
          <div className="flex flex-col gap-4">
            {/* terminal + logs row */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="h-[340px]">
                <TerminalUI />
              </div>
              <div className="h-[340px]">
                <LogPanel
                  title="Error Logs"
                  subtitle="pipeline #48291 · test:integration"
                  logs={errorLogs}
                  accent="error"
                />
              </div>
            </div>

            {/* agent logs */}
            <div className="h-[300px]">
              <LogPanel
                title="Agent Logs"
                subtitle="axolotl · reasoning trace"
                logs={agentLogs}
                accent="agent"
              />
            </div>

            {/* merge request */}
            <MergeRequestPanel />
          </div>
        </div>
      </main>

      <footer className="border-t border-border px-4 py-4 md:px-6">
        <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-2 font-mono text-xs text-muted-foreground">
          <span>axolotl agent runtime v1.4.2</span>
          <span>human-in-the-loop · last sync 14:32:46</span>
        </div>
      </footer>
    </div>
  )
}
