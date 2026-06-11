import type { LogLine, LogLevel } from "@/lib/axolotl-data"

const levelStyles: Record<LogLevel, string> = {
  error: "text-destructive",
  warn: "text-chart-4",
  info: "text-muted-foreground",
  debug: "text-muted-foreground/60",
  success: "text-chart-3",
}

const levelLabel: Record<LogLevel, string> = {
  error: "ERR",
  warn: "WRN",
  info: "INF",
  debug: "DBG",
  success: "OK ",
}

interface LogPanelProps {
  title: string
  subtitle: string
  logs: LogLine[]
  accent: "error" | "agent"
}

export function LogPanel({ title, subtitle, logs, accent }: LogPanelProps) {
  const dotColor = accent === "error" ? "bg-destructive" : "bg-accent"
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-border bg-[oklch(0.13_0.006_285)]">
      {/* window chrome */}
      <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <span className={`size-2 rounded-full ${dotColor}`} />
          <div className="leading-tight">
            <p className="text-sm font-medium text-foreground">{title}</p>
            <p className="font-mono text-[11px] text-muted-foreground">{subtitle}</p>
          </div>
        </div>
        <div className="flex gap-1.5">
          <span className="size-2.5 rounded-full bg-chart-4/60" />
          <span className="size-2.5 rounded-full bg-chart-3/60" />
          <span className="size-2.5 rounded-full bg-destructive/60" />
        </div>
      </div>

      {/* log body */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse font-mono text-xs">
          <tbody>
            {logs.map((line, i) => (
              <tr
                key={i}
                className="group align-top transition-colors hover:bg-secondary/40"
              >
                <td className="select-none border-r border-border/60 px-3 py-0.5 text-right text-muted-foreground/40 tabular-nums">
                  {i + 1}
                </td>
                <td className="select-none whitespace-nowrap px-2.5 py-0.5 text-muted-foreground/60">
                  {line.ts}
                </td>
                <td className={`select-none px-1 py-0.5 font-semibold ${levelStyles[line.level]}`}>
                  {levelLabel[line.level]}
                </td>
                <td className="whitespace-nowrap px-2 py-0.5 text-accent/70">
                  {line.source}
                </td>
                <td className={`w-full px-2 py-0.5 ${levelStyles[line.level]}`}>
                  {line.message}
                </td>
              </tr>
            ))}
            <tr>
              <td className="border-r border-border/60 px-3 py-0.5 text-right text-muted-foreground/40">
                {logs.length + 1}
              </td>
              <td colSpan={4} className="px-2.5 py-0.5">
                <span className="inline-block h-3.5 w-1.5 animate-pulse bg-accent/70 align-middle" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
