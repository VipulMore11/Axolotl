export type PipelineStatus = "running" | "failed" | "fixing" | "awaiting-approval" | "passed"

export type AgentStageKey =
  | "detect"
  | "fetch-logs"
  | "analyze"
  | "generate-fix"
  | "branch"
  | "commit"
  | "merge-request"
  | "approval"

export type StageState = "done" | "active" | "pending" | "error"

export interface AgentStage {
  key: AgentStageKey
  label: string
  description: string
  state: StageState
  durationMs?: number
}

export interface Pipeline {
  id: string
  project: string
  ref: string
  commit: string
  commitMessage: string
  author: string
  status: PipelineStatus
  trigger: string
  startedAt: string
}

export type LogLevel = "info" | "warn" | "error" | "debug" | "success"

export interface LogLine {
  ts: string
  level: LogLevel
  source: string
  message: string
}

export const pipeline: Pipeline = {
  id: "#48291",
  project: "platform-api",
  ref: "main",
  commit: "a3f29c1",
  commitMessage: "refactor: migrate auth middleware to edge runtime",
  author: "dana.okoro",
  status: "awaiting-approval",
  trigger: "push",
  startedAt: "14:32:08",
}

export const agentStages: AgentStage[] = [
  {
    key: "detect",
    label: "Detect Failure",
    description: "Job `test:integration` exited with code 1",
    state: "done",
    durationMs: 1200,
  },
  {
    key: "fetch-logs",
    label: "Fetch Pipeline Logs",
    description: "Pulled 4,812 lines across 3 failed jobs",
    state: "done",
    durationMs: 2400,
  },
  {
    key: "analyze",
    label: "Analyze Root Cause",
    description: "Gemini 2.5 Pro — confidence 94%",
    state: "done",
    durationMs: 8600,
  },
  {
    key: "generate-fix",
    label: "Generate Fix",
    description: "Patched `middleware/auth.ts` (+6 / -3)",
    state: "done",
    durationMs: 5100,
  },
  {
    key: "branch",
    label: "Create Branch",
    description: "axolotl/fix-edge-auth-48291",
    state: "done",
    durationMs: 800,
  },
  {
    key: "commit",
    label: "Commit Fix",
    description: "b91e7d2 — fix: await async cookies() in edge auth",
    state: "done",
    durationMs: 1100,
  },
  {
    key: "merge-request",
    label: "Raise Merge Request",
    description: "!1043 opened against `main`",
    state: "done",
    durationMs: 1500,
  },
  {
    key: "approval",
    label: "Human Approval",
    description: "Waiting on reviewer sign-off",
    state: "active",
  },
]

export const errorLogs: LogLine[] = [
  { ts: "14:32:09", level: "info", source: "runner", message: "Running on runner-7zq4 via gitlab-org..." },
  { ts: "14:32:10", level: "info", source: "test", message: "$ pnpm test:integration" },
  { ts: "14:32:14", level: "info", source: "vitest", message: "RUN  v2.1.4  /builds/platform-api" },
  { ts: "14:32:21", level: "warn", source: "vitest", message: "auth/session.test.ts > resolves session cookie (slow: 1842ms)" },
  { ts: "14:32:22", level: "error", source: "vitest", message: "FAIL  auth/middleware.test.ts > rejects expired tokens" },
  { ts: "14:32:22", level: "error", source: "node", message: "TypeError: cookies() should be awaited before using its value" },
  { ts: "14:32:22", level: "error", source: "node", message: "    at getToken (middleware/auth.ts:24:18)" },
  { ts: "14:32:22", level: "error", source: "node", message: "    at authMiddleware (middleware/auth.ts:41:22)" },
  { ts: "14:32:22", level: "error", source: "node", message: "    at processTicksAndRejections (node:internal/process/task_queues:95:5)" },
  { ts: "14:32:23", level: "error", source: "vitest", message: "  ⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯" },
  { ts: "14:32:23", level: "error", source: "vitest", message: "Test Files  1 failed | 18 passed (19)" },
  { ts: "14:32:23", level: "error", source: "vitest", message: "     Tests  1 failed | 213 passed (214)" },
  { ts: "14:32:24", level: "error", source: "runner", message: "ERROR: Job failed: exit code 1" },
  { ts: "14:32:24", level: "info", source: "runner", message: "Uploading artifacts for failed job..." },
]

export const agentLogs: LogLine[] = [
  { ts: "14:32:25", level: "info", source: "axolotl", message: "Pipeline #48291 transitioned to `failed` — engaging agent" },
  { ts: "14:32:26", level: "debug", source: "gitlab", message: "GET /projects/platform-api/jobs/9981/trace → 200 (4812 lines)" },
  { ts: "14:32:27", level: "info", source: "axolotl", message: "Tokenized trace → 6,204 tokens, isolating error window" },
  { ts: "14:32:28", level: "info", source: "gemini", message: "Prompting model `gemini-2.5-pro` with failure context + repo tree" },
  { ts: "14:32:36", level: "success", source: "gemini", message: "Root cause identified: synchronous cookies() call in edge runtime" },
  { ts: "14:32:36", level: "info", source: "gemini", message: "Confidence 0.94 — recommended single-file patch" },
  { ts: "14:32:37", level: "info", source: "axolotl", message: "Generating diff for middleware/auth.ts" },
  { ts: "14:32:42", level: "success", source: "axolotl", message: "Patch validated against local typecheck (tsc --noEmit)" },
  { ts: "14:32:43", level: "info", source: "git", message: "Created branch axolotl/fix-edge-auth-48291 from main@a3f29c1" },
  { ts: "14:32:44", level: "success", source: "git", message: "Committed b91e7d2 — fix: await async cookies() in edge auth" },
  { ts: "14:32:45", level: "info", source: "gitlab", message: "POST /merge_requests → 201 — !1043 opened" },
  { ts: "14:32:46", level: "warn", source: "axolotl", message: "Human-in-the-loop gate active — awaiting reviewer approval" },
]

export interface DiffLine {
  type: "context" | "add" | "remove" | "meta"
  oldNo?: number
  newNo?: number
  text: string
}

export const mergeRequest = {
  iid: "!1043",
  title: "fix: await async cookies() in edge auth middleware",
  sourceBranch: "axolotl/fix-edge-auth-48291",
  targetBranch: "main",
  author: "Axolotl Agent",
  status: "open" as const,
  approvalsRequired: 1,
  approvalsGiven: 0,
  filesChanged: 1,
  additions: 6,
  deletions: 3,
  pipelinePassing: true,
  description:
    "Automated fix raised by Axolotl. The integration suite failed because `cookies()` was called synchronously inside the edge auth middleware. Next.js 16 requires `cookies()` to be awaited. This patch makes `getToken` async and awaits the call site.",
  diffFile: "middleware/auth.ts",
  diff: [
    { type: "meta", text: "@@ -21,9 +21,9 @@ export async function authMiddleware(req: NextRequest) {" },
    { type: "context", oldNo: 21, newNo: 21, text: "import { cookies } from 'next/headers'" },
    { type: "context", oldNo: 22, newNo: 22, text: "" },
    { type: "remove", oldNo: 23, text: "function getToken() {" },
    { type: "remove", oldNo: 24, text: "  const store = cookies()" },
    { type: "remove", oldNo: 25, text: "  return store.get('session')?.value" },
    { type: "add", newNo: 23, text: "async function getToken() {" },
    { type: "add", newNo: 24, text: "  const store = await cookies()" },
    { type: "add", newNo: 25, text: "  return store.get('session')?.value" },
    { type: "context", oldNo: 26, newNo: 26, text: "}" },
    { type: "context", oldNo: 27, newNo: 27, text: "" },
    { type: "remove", oldNo: 28, text: "const token = getToken()" },
    { type: "add", newNo: 28, text: "const token = await getToken()" },
  ] as DiffLine[],
}

/* ----------------------------- Pipelines page ----------------------------- */

export interface PipelineRecord {
  id: string
  project: string
  ref: string
  commit: string
  commitMessage: string
  author: string
  status: PipelineStatus
  trigger: string
  startedAt: string
  duration: string
  agentEngaged: boolean
}

export const pipelines: PipelineRecord[] = [
  {
    id: "#48291",
    project: "platform-api",
    ref: "main",
    commit: "a3f29c1",
    commitMessage: "refactor: migrate auth middleware to edge runtime",
    author: "dana.okoro",
    status: "awaiting-approval",
    trigger: "push",
    startedAt: "14:32:08",
    duration: "21.4s",
    agentEngaged: true,
  },
  {
    id: "#48288",
    project: "platform-api",
    ref: "feat/billing-webhooks",
    commit: "7c10b4e",
    commitMessage: "feat: stripe webhook signature verification",
    author: "marcus.lee",
    status: "running",
    trigger: "merge_request",
    startedAt: "14:21:55",
    duration: "3m 12s",
    agentEngaged: false,
  },
  {
    id: "#48284",
    project: "web-dashboard",
    ref: "main",
    commit: "1f9ac02",
    commitMessage: "fix: hydration mismatch on settings route",
    author: "axolotl-agent",
    status: "passed",
    trigger: "push",
    startedAt: "13:58:41",
    duration: "2m 47s",
    agentEngaged: true,
  },
  {
    id: "#48279",
    project: "data-pipeline",
    ref: "main",
    commit: "b22e8d5",
    commitMessage: "chore: bump pyarrow to 17.0.0",
    author: "priya.nair",
    status: "failed",
    trigger: "schedule",
    startedAt: "13:40:12",
    duration: "5m 03s",
    agentEngaged: true,
  },
  {
    id: "#48275",
    project: "web-dashboard",
    ref: "feat/dark-mode",
    commit: "9e4c7a1",
    commitMessage: "feat: theme token system + persisted preference",
    author: "dana.okoro",
    status: "passed",
    trigger: "merge_request",
    startedAt: "13:12:30",
    duration: "2m 19s",
    agentEngaged: false,
  },
  {
    id: "#48270",
    project: "platform-api",
    ref: "main",
    commit: "5a7f0c3",
    commitMessage: "fix: connection pool exhaustion under load",
    author: "axolotl-agent",
    status: "passed",
    trigger: "push",
    startedAt: "12:47:08",
    duration: "1m 58s",
    agentEngaged: true,
  },
  {
    id: "#48266",
    project: "data-pipeline",
    ref: "feat/parquet-sink",
    commit: "c30b9f8",
    commitMessage: "feat: parquet sink with partitioning",
    author: "priya.nair",
    status: "fixing",
    trigger: "merge_request",
    startedAt: "12:30:44",
    duration: "—",
    agentEngaged: true,
  },
]

/* --------------------------- Merge Requests page -------------------------- */

export interface MergeRequestRecord {
  iid: string
  title: string
  project: string
  sourceBranch: string
  targetBranch: string
  author: string
  authorIsAgent: boolean
  status: "open" | "merged" | "closed"
  additions: number
  deletions: number
  filesChanged: number
  approvalsRequired: number
  approvalsGiven: number
  pipelinePassing: boolean
  openedAt: string
  rootCause: string
}

export const mergeRequests: MergeRequestRecord[] = [
  {
    iid: "!1043",
    title: "fix: await async cookies() in edge auth middleware",
    project: "platform-api",
    sourceBranch: "axolotl/fix-edge-auth-48291",
    targetBranch: "main",
    author: "Axolotl Agent",
    authorIsAgent: true,
    status: "open",
    additions: 6,
    deletions: 3,
    filesChanged: 1,
    approvalsRequired: 1,
    approvalsGiven: 0,
    pipelinePassing: true,
    openedAt: "14:32:45",
    rootCause: "Synchronous cookies() call in edge runtime",
  },
  {
    iid: "!1041",
    title: "fix: hydration mismatch on settings route",
    project: "web-dashboard",
    sourceBranch: "axolotl/fix-hydration-48284",
    targetBranch: "main",
    author: "Axolotl Agent",
    authorIsAgent: true,
    status: "merged",
    additions: 4,
    deletions: 2,
    filesChanged: 1,
    approvalsRequired: 1,
    approvalsGiven: 1,
    pipelinePassing: true,
    openedAt: "13:59:22",
    rootCause: "Date rendered without suppressHydrationWarning",
  },
  {
    iid: "!1038",
    title: "fix: connection pool exhaustion under load",
    project: "platform-api",
    sourceBranch: "axolotl/fix-pool-48270",
    targetBranch: "main",
    author: "Axolotl Agent",
    authorIsAgent: true,
    status: "merged",
    additions: 11,
    deletions: 5,
    filesChanged: 2,
    approvalsRequired: 1,
    approvalsGiven: 1,
    pipelinePassing: true,
    openedAt: "12:48:01",
    rootCause: "Pool max set below worker concurrency",
  },
  {
    iid: "!1035",
    title: "feat: stripe webhook signature verification",
    project: "platform-api",
    sourceBranch: "feat/billing-webhooks",
    targetBranch: "main",
    author: "marcus.lee",
    authorIsAgent: false,
    status: "open",
    additions: 142,
    deletions: 8,
    filesChanged: 6,
    approvalsRequired: 2,
    approvalsGiven: 1,
    pipelinePassing: false,
    openedAt: "11:20:14",
    rootCause: "—",
  },
  {
    iid: "!1029",
    title: "fix: retry transient S3 timeouts in data sink",
    project: "data-pipeline",
    sourceBranch: "axolotl/fix-s3-retry-48201",
    targetBranch: "main",
    author: "Axolotl Agent",
    authorIsAgent: true,
    status: "closed",
    additions: 9,
    deletions: 1,
    filesChanged: 1,
    approvalsRequired: 1,
    approvalsGiven: 0,
    pipelinePassing: true,
    openedAt: "Yesterday",
    rootCause: "Missing exponential backoff on PutObject",
  },
]

/* --------------------------- Agent Activity page -------------------------- */

export interface ActivityEvent {
  id: string
  time: string
  date: string
  type: "detection" | "analysis" | "fix" | "merge-request" | "approval" | "merged" | "rejected"
  pipeline: string
  project: string
  summary: string
  detail: string
  model?: string
  confidence?: number
}

export const activityFeed: ActivityEvent[] = [
  {
    id: "ev-091",
    time: "14:32:46",
    date: "Today",
    type: "merge-request",
    pipeline: "#48291",
    project: "platform-api",
    summary: "Raised merge request !1043",
    detail: "fix: await async cookies() in edge auth middleware — awaiting human approval",
    model: "gemini-2.5-pro",
    confidence: 94,
  },
  {
    id: "ev-090",
    time: "14:32:36",
    date: "Today",
    type: "analysis",
    pipeline: "#48291",
    project: "platform-api",
    summary: "Root cause identified",
    detail: "Synchronous cookies() call in edge runtime — single-file patch recommended",
    model: "gemini-2.5-pro",
    confidence: 94,
  },
  {
    id: "ev-089",
    time: "14:32:25",
    date: "Today",
    type: "detection",
    pipeline: "#48291",
    project: "platform-api",
    summary: "Pipeline failure detected",
    detail: "Job test:integration exited with code 1 — engaging agent",
  },
  {
    id: "ev-088",
    time: "13:59:48",
    date: "Today",
    type: "merged",
    pipeline: "#48284",
    project: "web-dashboard",
    summary: "Merge request !1041 merged",
    detail: "Approved by dana.okoro — deployed to production",
  },
  {
    id: "ev-087",
    time: "13:59:22",
    date: "Today",
    type: "fix",
    pipeline: "#48284",
    project: "web-dashboard",
    summary: "Generated fix for hydration mismatch",
    detail: "Added suppressHydrationWarning to timestamp render (+4 / -2)",
    model: "gemini-2.5-pro",
    confidence: 88,
  },
  {
    id: "ev-086",
    time: "12:48:01",
    date: "Today",
    type: "merged",
    pipeline: "#48270",
    project: "platform-api",
    summary: "Merge request !1038 merged",
    detail: "Approved by marcus.lee — connection pool fix deployed",
  },
  {
    id: "ev-085",
    time: "11:14:30",
    date: "Today",
    type: "rejected",
    pipeline: "#48201",
    project: "data-pipeline",
    summary: "Merge request !1029 rejected",
    detail: "Reviewer requested manual retry strategy — agent patch closed",
  },
]

/* ------------------------------ Agent config ------------------------------ */

export const watchedProjects = [
  { name: "platform-api", branch: "main", autoFix: true, failures24h: 2, fixed: 2 },
  { name: "web-dashboard", branch: "main", autoFix: true, failures24h: 1, fixed: 1 },
  { name: "data-pipeline", branch: "main", autoFix: false, failures24h: 1, fixed: 0 },
]

export const agentMetrics = {
  pipelinesMonitored: 1284,
  failuresDetected: 96,
  fixesGenerated: 91,
  mergeRequestsRaised: 91,
  autoMerged: 0,
  humanApproved: 88,
  successRate: 94.8,
  avgTimeToFix: "21.4s",
}
