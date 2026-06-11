export function AxolotlMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className={className}
    >
      <rect width="32" height="32" rx="8" fill="var(--primary)" />
      {/* axolotl head silhouette with external gills */}
      <path
        d="M16 8c-3.6 0-6.5 2.6-6.5 6.1 0 2.4 1.4 4.3 3.4 5.3.5.25.8.78.7 1.33l-.3 1.6c-.13.7.55 1.27 1.2 1l1.3-.55c.3-.13.65-.13.95 0l1.3.55c.65.27 1.33-.3 1.2-1l-.3-1.6c-.1-.55.2-1.08.7-1.33 2-1 3.4-2.9 3.4-5.3C22.5 10.6 19.6 8 16 8Z"
        fill="var(--primary-foreground)"
      />
      <path
        d="M9.5 12.5 6.4 11M9.2 15l-3.4.4M22.5 12.5 25.6 11M22.8 15l3.4.4"
        stroke="var(--primary-foreground)"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="13.6" cy="14" r="1.05" fill="var(--primary)" />
      <circle cx="18.4" cy="14" r="1.05" fill="var(--primary)" />
    </svg>
  )
}
