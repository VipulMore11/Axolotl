"use client"

import { useState } from "react"
import { TopBar } from "@/components/top-bar"
import { PageHeader } from "@/components/page-header"
import { AxolotlMark } from "@/components/axolotl-mark"
import { watchedProjects } from "@/lib/axolotl-data"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Slider } from "@/components/ui/slider"
import { GitBranch, Bot, ShieldCheck, KeyRound, Webhook, Plus } from "lucide-react"

function SettingCard({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: typeof Bot
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex items-start gap-3 border-b border-border px-5 py-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-secondary text-accent">
          <Icon className="size-4" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{description}</p>
        </div>
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

export default function SettingsPage() {
  const [confidence, setConfidence] = useState([85])
  const [requireApproval, setRequireApproval] = useState(true)
  const [autoBranch, setAutoBranch] = useState(true)
  const [notifyFailures, setNotifyFailures] = useState(true)
  const [projects, setProjects] = useState(watchedProjects)

  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <PageHeader
        title="Settings"
        description="Configure how Axolotl monitors your GitLab projects, reasons about failures, and enforces the human-in-the-loop approval gate."
        actions={
          <Button size="sm" className="bg-primary text-primary-foreground hover:bg-primary/90">
            Save changes
          </Button>
        }
      />
      <main className="mx-auto w-full max-w-[900px] px-4 py-6 md:px-6">
        <div className="flex flex-col gap-5">
          {/* watched projects */}
          <SettingCard
            icon={GitBranch}
            title="Watched Projects"
            description="GitLab repositories the agent monitors for pipeline failures."
          >
            <ul className="flex flex-col gap-2">
              {projects.map((p, idx) => (
                <li
                  key={p.name}
                  className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-secondary/40 px-3.5 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 font-mono text-sm text-foreground">
                      {p.name}
                      <span className="text-muted-foreground/50">/</span>
                      <span className="text-muted-foreground">{p.branch}</span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                      <span>{p.failures24h} failures · 24h</span>
                      <span className="text-muted-foreground/40">·</span>
                      <span className="text-chart-3">{p.fixed} auto-fixed</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <span className="text-[11px] text-muted-foreground">auto-engage</span>
                    <Switch
                      checked={p.autoFix}
                      onCheckedChange={(v) =>
                        setProjects((prev) =>
                          prev.map((x, i) => (i === idx ? { ...x, autoFix: v } : x)),
                        )
                      }
                    />
                  </div>
                </li>
              ))}
            </ul>
            <Button
              variant="outline"
              size="sm"
              className="mt-3 border-border bg-transparent text-muted-foreground hover:text-foreground"
            >
              <Plus className="size-4" />
              Add project
            </Button>
          </SettingCard>

          {/* model config */}
          <SettingCard
            icon={Bot}
            title="Analysis Model"
            description="The Gemini model and thresholds used for root-cause analysis."
          >
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Label className="text-sm text-foreground">Model</Label>
                <div className="flex items-center gap-2 rounded-md border border-border bg-secondary px-3 py-1.5 font-mono text-xs text-foreground">
                  <span className="size-1.5 rounded-full bg-chart-3" />
                  gemini-2.5-pro
                </div>
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <Label className="text-sm text-foreground">Minimum confidence to raise MR</Label>
                  <span className="font-mono text-sm text-accent">{confidence[0]}%</span>
                </div>
                <Slider value={confidence} onValueChange={setConfidence} min={50} max={99} step={1} />
                <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                  Fixes below this threshold are logged for review but no merge request is opened.
                </p>
              </div>
            </div>
          </SettingCard>

          {/* workflow / HITL */}
          <SettingCard
            icon={ShieldCheck}
            title="Human-in-the-Loop"
            description="Guardrails that keep a developer in control of every deployment."
          >
            <ul className="flex flex-col divide-y divide-border/60">
              {[
                {
                  label: "Require approval before merge",
                  desc: "Agent fixes always wait for a reviewer sign-off.",
                  checked: requireApproval,
                  set: setRequireApproval,
                  locked: true,
                },
                {
                  label: "Auto-create fix branch",
                  desc: "Commit fixes to a dedicated axolotl/* branch.",
                  checked: autoBranch,
                  set: setAutoBranch,
                },
                {
                  label: "Notify on detected failures",
                  desc: "Send a notification the moment a pipeline fails.",
                  checked: notifyFailures,
                  set: setNotifyFailures,
                },
              ].map((row) => (
                <li key={row.label} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm text-foreground">{row.label}</p>
                      {row.locked && (
                        <Badge variant="outline" className="border-primary/30 text-[10px] text-primary">
                          enforced
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">{row.desc}</p>
                  </div>
                  <Switch checked={row.checked} onCheckedChange={row.set} disabled={row.locked} />
                </li>
              ))}
            </ul>
          </SettingCard>

          {/* connections */}
          <SettingCard
            icon={Webhook}
            title="Connections"
            description="GitLab and webhook credentials used by the agent runtime."
          >
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="gitlab-url" className="text-sm text-foreground">
                  GitLab instance URL
                </Label>
                <Input
                  id="gitlab-url"
                  defaultValue="https://gitlab.com"
                  className="font-mono text-sm"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="token" className="flex items-center gap-1.5 text-sm text-foreground">
                  <KeyRound className="size-3.5 text-accent" />
                  Access token
                </Label>
                <Input
                  id="token"
                  type="password"
                  defaultValue="glpat-xxxxxxxxxxxxxxxxxxxx"
                  className="font-mono text-sm"
                />
              </div>
              <div className="flex items-center gap-2 rounded-md border border-chart-3/30 bg-chart-3/10 px-3 py-2 text-xs text-chart-3">
                <span className="size-1.5 rounded-full bg-chart-3" />
                Webhook verified · last event 14:32:08
              </div>
            </div>
          </SettingCard>

          {/* danger zone */}
          <section className="rounded-lg border border-destructive/30 bg-destructive/5">
            <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <AxolotlMark className="size-7" />
                <div>
                  <p className="text-sm font-medium text-foreground">Pause the agent</p>
                  <p className="text-xs text-muted-foreground">
                    Stop monitoring and fixing across all projects until resumed.
                  </p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="border-destructive/40 bg-transparent text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                Pause Axolotl
              </Button>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
