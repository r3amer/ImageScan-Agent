'use client'

import { useEffect, useRef, useState } from 'react'

interface UseWebSocketOptions {
  onOpen?: () => void
  onClose?: () => void
  onError?: () => void
  onMessage?: (message: WebSocketEventMap['message']) => void
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

interface WebSocketReturn {
  lastMessage: WebSocketEventMap['message'] | null
  readyState: number
  sendMessage: (message: string) => void
  connect: () => void
  disconnect: () => void
}

export function useWebSocket(
  url: string,
  options: UseWebSocketOptions = {}
): WebSocketReturn {
  const {
    onOpen,
    onClose,
    onError,
    onMessage,
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
  } = options

  const [lastMessage, setLastMessage] = useState<WebSocketEventMap['message'] | null>(null)
  const [readyState, setReadyState] = useState<number>(WebSocket.CLOSED)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempts = useRef(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()

  const connect = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setReadyState(WebSocket.OPEN)
        reconnectAttempts.current = 0
        onOpen?.()
      }

      ws.onclose = () => {
        setReadyState(WebSocket.CLOSED)
        onClose?.()

        // Attempt to reconnect
        if (reconnectAttempts.current < maxReconnectAttempts) {
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectAttempts.current++
            connect()
          }, reconnectInterval)
        }
      }

      ws.onerror = () => {
        setReadyState(WebSocket.CLOSED)
        onError?.()
      }

      ws.onmessage = (event) => {
        setLastMessage(event)
        onMessage?.(event)
      }
    } catch (error) {
      console.error('WebSocket connection error:', error)
      onError?.()
    }
  }

  const disconnect = () => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setReadyState(WebSocket.CLOSED)
  }

  const sendMessage = (message: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(message)
    }
  }

  // Auto-connect on mount
  useEffect(() => {
    connect()

    return () => {
      disconnect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  return {
    lastMessage,
    readyState,
    sendMessage,
    connect,
    disconnect,
  }
}
