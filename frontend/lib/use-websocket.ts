"use client"

import { useEffect, useRef, useState, useCallback } from "react"

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000"

export interface WSEvent {
  timestamp: string
  event_type: string
  message: string
  metadata?: Record<string, unknown>
}

interface UseAxolotlSocketReturn {
  events: WSEvent[]
  lastEvent: WSEvent | null
  isConnected: boolean
  clearEvents: () => void
}

/**
 * React hook for connecting to the Axolotl WebSocket.
 * Auto-reconnects on disconnect with exponential backoff.
 *
 * @param sessionId - The session/pipeline ID to subscribe to
 * @param enabled  - Whether the connection should be active
 */
export function useAxolotlSocket(
  sessionId: string | null,
  enabled = true
): UseAxolotlSocketReturn {
  const [events, setEvents] = useState<WSEvent[]>([])
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptRef = useRef(0)
  const maxReconnectAttempts = 10

  const clearEvents = useCallback(() => {
    setEvents([])
    setLastEvent(null)
  }, [])

  useEffect(() => {
    if (!sessionId || !enabled) {
      return
    }

    function connect() {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        return
      }

      const url = `${WS_BASE}/ws/${sessionId}`
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        console.log(`[WS] Connected to ${sessionId}`)
        setIsConnected(true)
        reconnectAttemptRef.current = 0
      }

      ws.onmessage = (event) => {
        try {
          const data: WSEvent = JSON.parse(event.data)
          setEvents((prev) => [...prev, data])
          setLastEvent(data)
        } catch (e) {
          console.warn("[WS] Failed to parse message:", event.data)
        }
      }

      ws.onclose = (event) => {
        console.log(`[WS] Disconnected from ${sessionId}`, event.code)
        setIsConnected(false)
        wsRef.current = null

        // Reconnect with exponential backoff
        if (reconnectAttemptRef.current < maxReconnectAttempts) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 30000)
          reconnectAttemptRef.current++
          console.log(`[WS] Reconnecting in ${delay}ms (attempt ${reconnectAttemptRef.current})`)
          reconnectTimeoutRef.current = setTimeout(connect, delay)
        }
      }

      ws.onerror = (error) => {
        console.error("[WS] Error:", error)
      }
    }

    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounted")
        wsRef.current = null
      }
      setIsConnected(false)
    }
  }, [sessionId, enabled])

  return { events, lastEvent, isConnected, clearEvents }
}
