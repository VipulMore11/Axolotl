"use client"

import { useEffect, useState, useCallback } from "react"
import { TopBar } from "@/components/top-bar"
import { PageHeader } from "@/components/page-header"
import { AxolotlMark } from "@/components/axolotl-mark"
import {
  getWatchedProjects,
  getAgentSettings,
  updateWatchedProject,
  updateAgentSettings,
  addWatchedProject,
  deleteWatchedProject,
  getGitLabRepos,
  type APIProject,
  type APIAgentSettings,
  type GitLabRepo,
} from "@/lib/api"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Slider } from "@/components/ui/slider"
import {
  GitBranch,
  Bot,
  ShieldCheck,
  Webhook,
  Plus,
  Loader2,
  Trash2,
  Check,
  Search,
  Globe,
  Lock,
  Star,
  GitFork,
  CheckCircle2,
  Plug,
  X,
} from "lucide-react"

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
  const [projects, setProjects] = useState<APIProject[]>([])
  const [settings, setSettings] = useState<APIAgentSettings>({
    confidence_threshold: 85,
    require_approval: true,
    auto_branch: true,
    notify_failures: true,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Repo browser state
  const [showRepoBrowser, setShowRepoBrowser] = useState(false)
  const [repos, setRepos] = useState<GitLabRepo[]>([])
  const [repoSearch, setRepoSearch] = useState("")
  const [loadingRepos, setLoadingRepos] = useState(false)
  const [connectingId, setConnectingId] = useState<number | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const [projData, settData] = await Promise.all([
          getWatchedProjects(),
          getAgentSettings(),
        ])
        setProjects(projData.projects)
        setSettings(settData.settings)
      } catch (e) {
        console.error("Failed to load settings:", e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // Fetch repos when browser opens or search changes
  const fetchRepos = useCallback(async (search: string) => {
    setLoadingRepos(true)
    try {
      const data = await getGitLabRepos(search, 1, 30)
      setRepos(data.repos)
    } catch (e) {
      console.error("Failed to fetch repos:", e)
    } finally {
      setLoadingRepos(false)
    }
  }, [])

  useEffect(() => {
    if (showRepoBrowser) {
      fetchRepos(repoSearch)
    }
  }, [showRepoBrowser, fetchRepos])

  // Debounced search
  useEffect(() => {
    if (!showRepoBrowser) return
    const timer = setTimeout(() => {
      fetchRepos(repoSearch)
    }, 400)
    return () => clearTimeout(timer)
  }, [repoSearch, showRepoBrowser, fetchRepos])

  async function handleSave() {
    setSaving(true)
    try {
      await updateAgentSettings(settings)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      console.error("Failed to save:", e)
    } finally {
      setSaving(false)
    }
  }

  async function handleConnectRepo(repo: GitLabRepo) {
    setConnectingId(repo.id)
    try {
      const result = await addWatchedProject({ project_id: String(repo.id) })
      // Mark as connected in the repo list
      setRepos((prev) =>
        prev.map((r) => (r.id === repo.id ? { ...r, already_connected: true } : r))
      )
      // Refresh projects list
      const data = await getWatchedProjects()
      setProjects(data.projects)
    } catch (e) {
      console.error("Failed to connect repo:", e)
    } finally {
      setConnectingId(null)
    }
  }

  async function handleToggleAutoFix(projectId: string, autoFix: boolean) {
    try {
      await updateWatchedProject(projectId, { auto_fix: autoFix })
      setProjects((prev) =>
        prev.map((p) => (p.project_id === projectId ? { ...p, auto_fix: autoFix } : p))
      )
    } catch (e) {
      console.error("Failed to update project:", e)
    }
  }

  async function handleDeleteProject(projectId: string) {
    try {
      await deleteWatchedProject(projectId)
      setProjects((prev) => prev.filter((p) => p.project_id !== projectId))
      // Update repo browser to reflect disconnection
      setRepos((prev) =>
        prev.map((r) =>
          String(r.id) === projectId ? { ...r, already_connected: false } : r
        )
      )
    } catch (e) {
      console.error("Failed to delete project:", e)
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <TopBar />
      <PageHeader
        title="Settings"
        description="Configure how Axolotl monitors your GitLab projects, reasons about failures, and enforces the human-in-the-loop approval gate."
        actions={
          <Button
            size="sm"
            className="bg-primary text-primary-foreground hover:bg-primary/90"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? (
              <Loader2 className="size-4 animate-spin" />
            ) : saved ? (
              <Check className="size-4" />
            ) : null}
            {saved ? "Saved" : "Save changes"}
          </Button>
        }
      />
      <main className="mx-auto w-full max-w-[900px] px-4 py-6 md:px-6">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading settings...
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            {/* ── Connected Projects ── */}
            <SettingCard
              icon={GitBranch}
              title="Connected Repositories"
              description="GitLab repositories Axolotl monitors for pipeline failures. Webhooks are registered automatically."
            >
              {projects.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-6 text-center">
                  <div className="flex size-12 items-center justify-center rounded-full border border-border bg-secondary mb-3">
                    <Plug className="size-5 text-muted-foreground" />
                  </div>
                  <p className="text-sm text-foreground font-medium">No repositories connected</p>
                  <p className="mt-1 max-w-sm text-xs text-muted-foreground">
                    Connect a GitLab repository to start monitoring its pipelines. Axolotl will automatically register a webhook.
                  </p>
                </div>
              ) : (
                <ul className="flex flex-col gap-2">
                  {projects.map((p) => (
                    <li
                      key={p.project_id}
                      className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-secondary/40 px-3.5 py-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 font-mono text-sm text-foreground">
                          {p.project_name}
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                          <span>ID: {p.project_id}</span>
                          <span className="text-muted-foreground/40">·</span>
                          <span>branch: {p.branch}</span>
                          {p.webhook_registered ? (
                            <Badge className="gap-1 border-chart-3/30 bg-chart-3/10 text-chart-3 text-[10px] px-1.5 py-0 hover:bg-chart-3/10">
                              <Webhook className="size-3" />
                              webhook active
                            </Badge>
                          ) : (
                            <Badge className="gap-1 border-chart-4/30 bg-chart-4/10 text-chart-4 text-[10px] px-1.5 py-0 hover:bg-chart-4/10">
                              <Webhook className="size-3" />
                              webhook pending
                            </Badge>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2.5">
                        <span className="text-[11px] text-muted-foreground">auto-fix</span>
                        <Switch
                          checked={p.auto_fix}
                          onCheckedChange={(v) => handleToggleAutoFix(p.project_id, v)}
                        />
                        <button
                          onClick={() => handleDeleteProject(p.project_id)}
                          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                          title="Disconnect repository"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {/* Connect button */}
              <div className="mt-4">
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full gap-2 border-primary/30 bg-primary/5 text-primary hover:bg-primary/10 hover:text-primary"
                  onClick={() => setShowRepoBrowser(!showRepoBrowser)}
                >
                  {showRepoBrowser ? (
                    <>
                      <X className="size-4" />
                      Close repo browser
                    </>
                  ) : (
                    <>
                      <Plus className="size-4" />
                      Connect a GitLab repository
                    </>
                  )}
                </Button>
              </div>

              {/* ── Repo Browser ── */}
              {showRepoBrowser && (
                <div className="mt-4 rounded-lg border border-primary/20 bg-background">
                  {/* search bar */}
                  <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
                    <Search className="size-4 text-muted-foreground" />
                    <input
                      value={repoSearch}
                      onChange={(e) => setRepoSearch(e.target.value)}
                      placeholder="Search your GitLab repositories..."
                      className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
                      autoFocus
                    />
                    {loadingRepos && <Loader2 className="size-4 animate-spin text-primary" />}
                  </div>

                  {/* repo list */}
                  <div className="max-h-[360px] overflow-y-auto">
                    {repos.length === 0 && !loadingRepos ? (
                      <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                        {repoSearch ? "No repositories found." : "Loading..."}
                      </div>
                    ) : (
                      <ul className="divide-y divide-border/60">
                        {repos.map((repo) => (
                          <li
                            key={repo.id}
                            className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-secondary/40"
                          >
                            {/* repo avatar */}
                            <div className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-secondary text-xs font-bold text-muted-foreground uppercase">
                              {repo.avatar_url ? (
                                <img
                                  src={repo.avatar_url}
                                  alt=""
                                  className="size-9 rounded-md object-cover"
                                />
                              ) : (
                                repo.name.slice(0, 2)
                              )}
                            </div>

                            {/* repo info */}
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <p className="truncate text-sm font-medium text-foreground">
                                  {repo.path_with_namespace}
                                </p>
                                {repo.visibility === "private" ? (
                                  <Lock className="size-3 shrink-0 text-chart-4" />
                                ) : (
                                  <Globe className="size-3 shrink-0 text-muted-foreground" />
                                )}
                              </div>
                              <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted-foreground">
                                {repo.description && (
                                  <span className="max-w-[240px] truncate">{repo.description}</span>
                                )}
                                <span className="flex items-center gap-1">
                                  <GitBranch className="size-3" />
                                  {repo.default_branch}
                                </span>
                                {repo.star_count > 0 && (
                                  <span className="flex items-center gap-1">
                                    <Star className="size-3" />
                                    {repo.star_count}
                                  </span>
                                )}
                                {repo.forks_count > 0 && (
                                  <span className="flex items-center gap-1">
                                    <GitFork className="size-3" />
                                    {repo.forks_count}
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* connect button */}
                            {repo.already_connected ? (
                              <Badge className="gap-1.5 border-chart-3/30 bg-chart-3/10 text-chart-3 hover:bg-chart-3/10">
                                <CheckCircle2 className="size-3.5" />
                                Connected
                              </Badge>
                            ) : (
                              <Button
                                size="sm"
                                className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
                                disabled={connectingId === repo.id}
                                onClick={() => handleConnectRepo(repo)}
                              >
                                {connectingId === repo.id ? (
                                  <Loader2 className="size-3.5 animate-spin" />
                                ) : (
                                  <Plug className="size-3.5" />
                                )}
                                Connect
                              </Button>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </SettingCard>

            {/* ── Model Config ── */}
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
                    <span className="font-mono text-sm text-accent">{settings.confidence_threshold}%</span>
                  </div>
                  <Slider
                    value={[settings.confidence_threshold]}
                    onValueChange={([v]) => setSettings((s) => ({ ...s, confidence_threshold: v }))}
                    min={50}
                    max={99}
                    step={1}
                  />
                  <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                    Fixes below this threshold are logged for review but no merge request is opened.
                  </p>
                </div>
              </div>
            </SettingCard>

            {/* ── Human-in-the-Loop ── */}
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
                    checked: settings.require_approval,
                    key: "require_approval" as const,
                    locked: true,
                  },
                  {
                    label: "Auto-create fix branch",
                    desc: "Commit fixes to a dedicated axolotl/* branch.",
                    checked: settings.auto_branch,
                    key: "auto_branch" as const,
                  },
                  {
                    label: "Notify on detected failures",
                    desc: "Send a notification the moment a pipeline fails.",
                    checked: settings.notify_failures,
                    key: "notify_failures" as const,
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
                    <Switch
                      checked={row.checked}
                      onCheckedChange={(v) => setSettings((s) => ({ ...s, [row.key]: v }))}
                      disabled={row.locked}
                    />
                  </li>
                ))}
              </ul>
            </SettingCard>

            {/* ── Connections ── */}
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
                    readOnly
                  />
                </div>
                <div className="flex items-center gap-2 rounded-md border border-chart-3/30 bg-chart-3/10 px-3 py-2 text-xs text-chart-3">
                  <span className="size-1.5 rounded-full bg-chart-3" />
                  Connected via OAuth
                </div>
              </div>
            </SettingCard>

            {/* ── Danger Zone ── */}
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
        )}
      </main>
    </div>
  )
}
