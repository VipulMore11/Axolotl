import type { ReactNode } from "react"

interface PageHeaderProps {
  title: string
  description: string
  meta?: ReactNode
  actions?: ReactNode
}

export function PageHeader({ title, description, meta, actions }: PageHeaderProps) {
  return (
    <section className="border-b border-border bg-card/40">
      <div className="mx-auto w-full max-w-[1600px] px-4 py-6 md:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <h1 className="text-balance text-xl font-semibold tracking-tight text-foreground">
              {title}
            </h1>
            <p className="mt-1.5 max-w-2xl text-pretty text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
        {meta && <div className="mt-5">{meta}</div>}
      </div>
    </section>
  )
}
