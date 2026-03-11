'use client'

import { useState, useEffect, useCallback } from 'react'
import { Scan, Clock } from 'lucide-react'
import ScanInput from './ScanInput'
import ScanProgress from './ScanProgress'
import ScanResults from './ScanResults'
import ScanHistory from './ScanHistory'
import EventLog from './EventLog'
import { useWebSocket } from '@/hooks/useWebSocket'
import type { ScanResult, ScanEvent } from '@/types/scan'

interface ScanInterfaceProps {
  sessionId: string
}

export default function ScanInterface({ sessionId }: ScanInterfaceProps) {
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [events, setEvents] = useState<ScanEvent[]>([])
  const [view, setView] = useState<'scan' | 'history'>('scan')
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking')

  // WebSocket connection
  // WebSocket 无法通过 Next.js rewrites 代理，需要直接连接后端
  const getWsUrl = () => {
    if (process.env.NEXT_PUBLIC_API_URL) {
      return process.env.NEXT_PUBLIC_API_URL.replace('http', 'ws')
    }
    if (typeof window !== 'undefined') {
      return (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
        ? 'ws://localhost:8000'
        : `ws://${window.location.hostname}:8000`
    }
    return 'ws://localhost:8000'
  }

  const { lastMessage } = useWebSocket(
    `${getWsUrl()}/api/events/ws/${sessionId}`,
    {
      onOpen: () => {
        setConnectionStatus('connected')
        setEvents(prev => [{
          type: 'system.connected',
          source: 'websocket',
          data: { message: 'WebSocket connection established' },
          timestamp: new Date().toISOString(),
        }, ...prev])
      },
      onClose: () => {
        setConnectionStatus('disconnected')
      },
      onError: () => {
        setConnectionStatus('disconnected')
        setEvents(prev => [{
          type: 'error',
          source: 'websocket',
          data: { message: 'Failed to connect to WebSocket. Is the backend running?' },
          timestamp: new Date().toISOString(),
        }, ...prev])
      },
    }
  )

  // Check connection status on mount
  useEffect(() => {
    const checkStatus = async () => {
      try {
        // 使用 Next.js 反向代理
        const res = await fetch('/health')
        if (res.ok) {
          setConnectionStatus('connected')
        } else {
          setConnectionStatus('disconnected')
        }
      } catch {
        setConnectionStatus('disconnected')
      }
    }
    checkStatus()
  }, [])

  // Handle incoming WebSocket events
  useEffect(() => {
    if (lastMessage) {
      try {
        const event: ScanEvent = JSON.parse(lastMessage.data)

        // 添加调试日志
        console.log('[WebSocket] 收到事件:', event.type, event.data?.task_id)

        // Add to event log
        setEvents(prev => [
          {
            ...event,
            timestamp: event.timestamp || new Date().toISOString()
          },
          ...prev
        ].slice(0, 100))

        // Handle task events
        if (event.type === 'task.started' && event.data?.task_id) {
          setCurrentTaskId(event.data.task_id)
          setScanResult({
            task_id: event.data.task_id,
            image_name: event.data.image_name || 'Unknown',
            status: 'running',
            credentials: [],
            started_at: new Date().toISOString(),
          })
        }

        if (event.type === 'task.completed' && event.data?.task_id) {
          // 即使 prev 是 null，也创建新的结果对象
          setScanResult(prev => ({
            ...(prev || {
              task_id: event.data.task_id,
              image_name: event.data.image_name || 'Unknown',
              credentials: [],
            }),
            status: 'completed',
            completed_at: new Date().toISOString(),
            credentials: event.data?.credentials || (prev?.credentials || []),
            statistics: event.data?.statistics,
            duration: event.data?.duration,
          }))
        }

        if (event.type === 'task.failed' && event.data?.task_id) {
          // 即使 prev 是 null，也创建新的结果对象
          setScanResult(prev => ({
            ...(prev || {
              task_id: event.data.task_id,
              image_name: event.data.image_name || 'Unknown',
              credentials: [],
            }),
            status: 'failed',
            completed_at: new Date().toISOString(),
          }))
        }

        if (event.type === 'credential.found' && scanResult && event.data) {
          const credential = event.data.credential
          if (credential) {
            setScanResult(prev => prev ? {
              ...prev,
              credentials: [...prev.credentials, credential],
            } : null)
          }
        }

        // Update progress events
        if (event.type === 'layer.completed' || event.type === 'file.scanned') {
          const stats = event.data?.statistics
          setScanResult(prev => prev ? {
            ...prev,
            statistics: {
              ...prev.statistics,
              ...(stats || {}),
            }
          } : null)
        }

      } catch (error) {
        console.error('Failed to parse WebSocket message:', error)
      }
    }
  }, [lastMessage, scanResult])

  const handleStartScan = useCallback(async (imageName: string) => {
    try {
      // 使用 Next.js 反向代理
      const response = await fetch('/api/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `scan ${imageName}`,
          session_id: sessionId,
        }),
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`API Error ${response.status}: ${errorText}`)
      }

      const data = await response.json()

      if (data.task_id) {
        setCurrentTaskId(data.task_id)
        setScanResult({
          task_id: data.task_id,
          image_name: imageName,
          status: 'running',
          credentials: [],
          started_at: new Date().toISOString(),
        })
      }
    } catch (error) {
      console.error('Error starting scan:', error)
      const errorMessage = error instanceof Error ? error.message : 'Unknown error'
      setEvents(prev => [{
        type: 'error',
        source: 'system',
        data: { message: errorMessage },
        timestamp: new Date().toISOString(),
      }, ...prev])
    }
  }, [sessionId])

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Status bar - simplified */}
      <div className="mb-8 flex items-center justify-between text-xs font-mono">
        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-2">
            <span className={`w-1.5 h-1.5 rounded-full ${connectionStatus === 'connected' ? 'bg-neon-green animate-pulse' : connectionStatus === 'checking' ? 'bg-neon-orange animate-pulse' : 'bg-neon-red'}`} />
            <span className={connectionStatus === 'connected' ? 'text-neon-green' : connectionStatus === 'checking' ? 'text-neon-orange' : 'text-neon-red'}>
              {connectionStatus === 'connected' ? 'SYSTEM ONLINE' : connectionStatus === 'checking' ? 'CHECKING...' : 'OFFLINE'}
            </span>
          </div>
          {currentTaskId && (
            <span className="text-terminal-muted">
              TASK_ID: <span className="text-neon-cyan">{currentTaskId.slice(0, 8)}</span>
            </span>
          )}
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={() => setView('scan')}
            className={`px-4 py-1.5 text-xs font-mono border transition-all ${
              view === 'scan'
                ? 'border-neon-green text-neon-green'
                : 'border-terminal-muted text-terminal-muted hover:border-neon-green hover:text-neon-green'
            }`}
          >
            SCAN
          </button>
          <button
            onClick={() => setView('history')}
            className={`px-4 py-1.5 text-xs font-mono border transition-all ${
              view === 'history'
                ? 'border-neon-green text-neon-green'
                : 'border-terminal-muted text-terminal-muted hover:border-neon-green hover:text-neon-green'
            }`}
          >
            HISTORY
          </button>
        </div>
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column */}
        <div className="lg:col-span-2 space-y-6">
          {view === 'scan' ? (
            <>
              <ScanInput
                onStartScan={handleStartScan}
                isScanning={scanResult?.status === 'running'}
              />

              {scanResult && (
                <ScanProgress
                  result={scanResult}
                  events={events}
                />
              )}

              {scanResult && scanResult.status === 'completed' && (
                <ScanResults result={scanResult} />
              )}

              {scanResult && scanResult.status === 'failed' && (
                <div className="data-card border-neon-red">
                  <div className="text-neon-red font-mono text-sm mb-2">SCAN FAILED</div>
                  <p className="text-terminal-muted text-xs">
                    An error occurred during the scan. Check the event log for details.
                  </p>
                </div>
              )}
            </>
          ) : (
            <ScanHistory />
          )}
        </div>

        {/* Right column - Event log */}
        <div className="lg:col-span-1">
          <EventLog events={events} />
        </div>
      </div>
    </div>
  )
}
