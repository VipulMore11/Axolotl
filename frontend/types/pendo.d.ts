interface Pendo {
  track(eventName: string, properties?: Record<string, string | number | boolean>): void
}

declare const pendo: Pendo | undefined
