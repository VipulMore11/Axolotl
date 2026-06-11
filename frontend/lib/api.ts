/**
 * Centralized API client for Axolotl frontend.
 * All API calls go through fetchWithAuth which adds JWT headers.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem("axolotl_token")
}

/**
 * Fetch wrapper that injects the JWT Authorization header.
 */
export async function fetchWithAuth(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = getToken()
  const headers = new Headers(options.headers || {})
  if (token) {
    headers.set("Authorization", `Bearer ${token}`)
  }
  headers.set("Content-Type", "application/json")

  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })
}

/**
 * Generic typed GET helper.
 */
async function apiGet<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(path)
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${path}`)
  }
  return res.json()
}

/**
 * Generic typed POST helper.
 */
async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetchWithAuth(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${path}`)
  }
  return res.json()
}

/**
 * Generic typed PUT helper.
 */
async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetchWithAuth(path, {
    method: "PUT",
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${path}`)
  }
  return res.json()
}

/**
 * Generic typed DELETE helper.
 */
async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(path, { method: "DELETE" })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${path}`)
  }
  return res.json()
}

// ── Dashboard ────────────────────────────────────────────────────────

export function getDashboardSummary() {
  return apiGet<{
    projects_count: number
    metrics: {
      failures_detected: number
      fixes_generated: number
      merge_requests_raised: number
      success_rate: number
      human_approved: number
      auto_merged: number
    }
  }>("/api/dashboard/summary")
}

export function getActiveSession() {
  return apiGet<{
    active_session: {
      session_id: string
      events: Array<{
        _id: string
        timestamp: string
        session_id: string
        event_type: string
        message: string
        metadata?: Record<string, unknown>
      }>
      is_complete: boolean
    } | null
  }>("/api/dashboard/active-session")
}

// ── Pipelines ────────────────────────────────────────────────────────

export interface APIPipeline {
  id: number
  iid?: number
  project_id: string
  project_name: string
  ref: string
  sha: string
  status: string
  source: string
  created_at: string
  updated_at: string
  duration: number | null
  web_url: string
  agent_engaged: boolean
}

export function getPipelines(page = 1, perPage = 20) {
  return apiGet<{ pipelines: APIPipeline[]; total: number }>(
    `/api/pipelines?page=${page}&per_page=${perPage}`
  )
}

export function getPipelineDetail(pipelineId: string, projectId: string) {
  return apiGet<{ pipeline: unknown; jobs: unknown[] }>(
    `/api/pipelines/${pipelineId}?project_id=${projectId}`
  )
}

// ── Merge Requests ───────────────────────────────────────────────────

export interface APIMergeRequest {
  iid: string
  raw_iid: number
  title: string
  project: string
  project_id: string
  source_branch: string
  target_branch: string
  author: string
  author_username: string
  author_is_agent: boolean
  author_avatar_url: string
  status: "open" | "merged" | "closed"
  additions: number
  deletions: number
  files_changed: number
  approvals_required: number
  approvals_given: number
  pipeline_passing: boolean
  opened_at: string
  web_url: string
  description: string
  root_cause: string
}

export function getMergeRequests(state = "all") {
  return apiGet<{ merge_requests: APIMergeRequest[]; total: number }>(
    `/api/merge-requests?state=${state}`
  )
}

export function getMergeRequestDetail(projectId: string, mrIid: number) {
  return apiGet<{ merge_request: unknown; changes: unknown[] }>(
    `/api/merge-requests/${projectId}/${mrIid}`
  )
}

export function approveMergeRequest(projectId: string, mrIid: number) {
  return apiPost<{ status: string }>(`/api/merge-requests/${projectId}/${mrIid}/approve`)
}

export function mergeMergeRequest(projectId: string, mrIid: number) {
  return apiPost<{ status: string }>(`/api/merge-requests/${projectId}/${mrIid}/merge`)
}

export function rejectMergeRequest(projectId: string, mrIid: number) {
  return apiPost<{ status: string }>(`/api/merge-requests/${projectId}/${mrIid}/reject`)
}

// ── Activity ─────────────────────────────────────────────────────────

export interface APIActivityEvent {
  id: string
  time: string
  date: string
  type: string
  pipeline: string
  project: string
  summary: string
  detail: string
  session_id: string
  model?: string
  confidence?: number
}

export function getActivityEvents(limit = 50) {
  return apiGet<{ events: APIActivityEvent[]; total: number }>(
    `/api/activity/events?limit=${limit}`
  )
}

export function getActivityMetrics() {
  return apiGet<{
    metrics: {
      failures_detected: number
      fixes_generated: number
      merge_requests_raised: number
      success_rate: number
      human_approved: number
      auto_merged: number
    }
  }>("/api/activity/metrics")
}

// ── Settings ─────────────────────────────────────────────────────────

export interface GitLabRepo {
  id: number
  name: string
  path_with_namespace: string
  description: string
  web_url: string
  default_branch: string
  avatar_url: string | null
  last_activity_at: string
  visibility: string
  star_count: number
  forks_count: number
  already_connected: boolean
}

export interface APIProject {
  project_id: string
  project_name: string
  gitlab_url: string
  branch: string
  auto_fix: boolean
  webhook_registered: boolean
  webhook_id: number | null
}

export interface APIAgentSettings {
  confidence_threshold: number
  require_approval: boolean
  auto_branch: boolean
  notify_failures: boolean
}

export function getGitLabRepos(search = "", page = 1, perPage = 20) {
  return apiGet<{ repos: GitLabRepo[]; total: number }>(
    `/api/settings/gitlab-repos?search=${encodeURIComponent(search)}&page=${page}&per_page=${perPage}`
  )
}

export function getWatchedProjects() {
  return apiGet<{ projects: APIProject[] }>("/api/settings/projects")
}

export function addWatchedProject(data: { project_id: string; gitlab_url?: string; auto_fix?: boolean }) {
  return apiPost<{ status: string; project_id: string; webhook_registered: boolean }>("/api/settings/projects", data)
}

export function updateWatchedProject(projectId: string, data: { auto_fix?: boolean }) {
  return apiPut<{ status: string }>(`/api/settings/projects/${projectId}`, data)
}

export function deleteWatchedProject(projectId: string) {
  return apiDelete<{ status: string }>(`/api/settings/projects/${projectId}`)
}

export function getAgentSettings() {
  return apiGet<{ settings: APIAgentSettings }>("/api/settings/agent")
}

export function updateAgentSettings(data: Partial<APIAgentSettings>) {
  return apiPut<{ status: string; settings: APIAgentSettings }>("/api/settings/agent", data)
}

