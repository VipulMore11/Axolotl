"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { AxolotlMark } from "@/components/axolotl-mark"
import { Badge } from "@/components/ui/badge"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Bell, BookOpen, GitBranch, Settings } from "lucide-react"

const navItems = [
  { label: "Overview", href: "/" },
  { label: "Pipelines", href: "/pipelines" },
  { label: "Merge Requests", href: "/merge-requests" },
  { label: "Agent Activity", href: "/activity" },
  { label: "Settings", href: "/settings" },
]

export function TopBar() {
  const pathname = usePathname()
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="flex h-14 items-center gap-3 px-4 md:px-6">
        <div className="flex items-center gap-2.5">
          <AxolotlMark className="size-7 shrink-0" />
          <span className="font-semibold tracking-tight text-foreground">Axolotl</span>
          <Badge
            variant="outline"
            className="hidden border-accent/30 bg-accent/10 font-mono text-[10px] uppercase tracking-wider text-accent sm:inline-flex"
          >
            agent online
          </Badge>
        </div>

        <div className="mx-2 hidden items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 font-mono text-xs text-muted-foreground lg:flex">
          <GitBranch className="size-3.5 text-accent" />
          <span className="text-foreground">platform-api</span>
          <span className="text-muted-foreground/50">/</span>
          <span>main</span>
        </div>

        <nav className="ml-auto hidden items-center gap-1 md:flex">
          {navItems.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
            return (
              <Link
                key={item.label}
                href={item.href}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                }`}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>

        <div className="ml-auto flex items-center gap-1 md:ml-3">
          <button className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
            <BookOpen className="size-4" />
            <span className="sr-only">Docs</span>
          </button>
          <button className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
            <Bell className="size-4" />
            <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-primary" />
            <span className="sr-only">Notifications</span>
          </button>
          <button className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
            <Settings className="size-4" />
            <span className="sr-only">Settings</span>
          </button>
          <Avatar className="ml-1 size-7">
            <AvatarFallback className="bg-secondary text-xs text-foreground">DO</AvatarFallback>
          </Avatar>
        </div>
      </div>
    </header>
  )
}
