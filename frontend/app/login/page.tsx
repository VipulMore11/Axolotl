import { Button } from "@/components/ui/button"
import { AxolotlMark } from "@/components/axolotl-mark"
import { GitBranch, ShieldCheck, Zap } from "lucide-react"

export default function LoginPage() {
  return (
    <div className="flex min-h-screen bg-background text-foreground selection:bg-primary/30">
      {/* Left side: branding & pitch */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden border-r border-border bg-card/30 p-10 lg:flex">
        {/* Glow effects */}
        <div className="absolute -left-1/4 -top-1/4 size-[500px] rounded-full bg-primary/20 blur-[100px]" />
        <div className="absolute -bottom-1/4 -right-1/4 size-[500px] rounded-full bg-accent/20 blur-[100px]" />

        <div className="relative z-10 flex items-center gap-3">
          <AxolotlMark className="size-8" />
          <span className="text-xl font-bold tracking-tight">Axolotl</span>
        </div>

        <div className="relative z-10 max-w-md">
          <h1 className="text-4xl font-bold tracking-tight text-foreground lg:text-5xl">
            Self-healing CI/CD
            <br />
            <span className="text-muted-foreground">with human approval.</span>
          </h1>
          <p className="mt-6 text-base leading-relaxed text-muted-foreground">
            Connect your GitLab account to let Axolotl automatically monitor your pipelines,
            diagnose failures using Gemini, and raise fix merge requests for your review.
          </p>

          <div className="mt-10 flex flex-col gap-5">
            <div className="flex items-start gap-4">
              <div className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-secondary text-primary">
                <Zap className="size-4" />
              </div>
              <div>
                <h3 className="font-semibold text-foreground">Instant Analysis</h3>
                <p className="text-sm text-muted-foreground">Root cause detection in seconds.</p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-secondary text-accent">
                <GitBranch className="size-4" />
              </div>
              <div>
                <h3 className="font-semibold text-foreground">Auto-branching</h3>
                <p className="text-sm text-muted-foreground">Fixes are pushed to dedicated branches.</p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-secondary text-chart-3">
                <ShieldCheck className="size-4" />
              </div>
              <div>
                <h3 className="font-semibold text-foreground">Human-in-the-loop</h3>
                <p className="text-sm text-muted-foreground">Nothing deploys without your approval.</p>
              </div>
            </div>
          </div>
        </div>

        <div className="relative z-10 font-mono text-xs text-muted-foreground">
          v1.4.2 · agent runtime
        </div>
      </div>

      {/* Right side: Login form */}
      <div className="flex w-full flex-col items-center justify-center p-8 lg:w-1/2">
        <div className="mx-auto flex w-full max-w-sm flex-col justify-center space-y-6">
          <div className="flex flex-col space-y-2 text-center lg:text-left">
            <div className="flex items-center justify-center lg:hidden mb-6">
              <AxolotlMark className="size-10" />
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">Welcome back</h1>
            <p className="text-sm text-muted-foreground">
              Sign in with your GitLab account to access the dashboard
            </p>
          </div>

          <div className="grid gap-4">
            <form action={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/auth/gitlab/login`} method="GET">
              <Button type="submit" className="w-full bg-primary text-primary-foreground hover:bg-primary/90 h-11">
                <svg
                  className="mr-2 size-5"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M22.65 14.39L12 22.13L1.35 14.39C0.85 14.03 0.64 13.38 0.82 12.8L3.63 4.2C3.81 3.66 4.34 3.32 4.91 3.38C5.48 3.44 5.92 3.86 6.01 4.43L7.71 14.86L12 18.02L16.29 14.86L17.99 4.43C18.08 3.86 18.52 3.44 19.09 3.38C19.66 3.32 20.19 3.66 20.37 4.2L23.18 12.8C23.36 13.38 23.15 14.03 22.65 14.39Z"
                    fill="currentColor"
                  />
                </svg>
                Login with GitLab
              </Button>
            </form>
          </div>

          <p className="px-8 text-center text-xs text-muted-foreground lg:px-0 lg:text-left">
            By clicking login, you agree to our{" "}
            <a href="#" className="underline underline-offset-4 hover:text-primary">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="#" className="underline underline-offset-4 hover:text-primary">
              Privacy Policy
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  )
}
