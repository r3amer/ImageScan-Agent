'use client'

import { useState, useEffect } from 'react'
import { Clock, ExternalLink } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

interface HistoryItem {
  task_id: string
  image_name: string
  status: 'running' | 'completed' | 'failed'
  created_at: string
  completed_at?: string
  credentials_count: number
  duration?: number
}

interface ScanResultFromAPI {
  task_id: string
  image_name: string
  status: 'running' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  credentials: Array<any>
  duration?: number
}

export default function ScanHistory() {
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchHistory()
  }, [])

  const fetchHistory = async () => {
    try {
      // 使用 Next.js 反向代理
      const response = await fetch('/api/scan/history?limit=10')
      if (response.ok) {
        const data: ScanResultFromAPI[] = await response.json()
        // 映射 API 响应到前端期望的格式
        const mappedData: HistoryItem[] = data.map((item) => ({
          task_id: item.task_id,
          image_name: item.image_name,
          status: item.status,
          created_at: item.started_at || new Date().toISOString(),
          completed_at: item.completed_at,
          credentials_count: item.credentials?.length || 0,
          duration: item.duration,
        }))
        setHistory(mappedData)
      }
    } catch (error) {
      console.error('Failed to fetch history:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="data-card">
      {/* Header */}
      <div className="flex items-center space-x-3 mb-6">
        <Clock className="w-6 h-6 text-neon-green" />
        <div>
          <h2 className="text-lg font-bold text-neon-green">SCAN HISTORY</h2>
          <p className="mono-label">Recent scan results</p>
        </div>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-12 text-terminal-dim">
          <div className="w-8 h-8 border-2 border-terminal-muted border-t-neon-green rounded-full animate-spin mb-4" />
          <p className="text-sm">Loading history...</p>
        </div>
      ) : history.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-terminal-dim">
          <Clock className="w-12 h-12 mb-4 opacity-50" />
          <p className="text-sm">No scan history yet</p>
          <p className="text-xs mt-2">Completed scans will appear here</p>
        </div>
      ) : (
        <div className="space-y-3">
          {history.map((item) => (
            <HistoryCard key={item.task_id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}

function HistoryCard({ item }: { item: HistoryItem }) {
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'text-neon-green'
      case 'running': return 'text-neon-orange'
      case 'failed': return 'text-neon-red'
      default: return 'text-terminal-muted'
    }
  }

  const getStatusBg = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-neon-green/10 border-neon-green'
      case 'running': return 'bg-neon-orange/10 border-neon-orange'
      case 'failed': return 'bg-neon-red/10 border-neon-red'
      default: return 'bg-terminal-dark border-terminal-muted'
    }
  }

  return (
    <div className={`bg-terminal-black/50 border p-4 hover:border-terminal-light/50 transition-all`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <h4 className="font-mono text-neon-cyan truncate mb-1">
            {item.image_name}
          </h4>
          <p className="text-xs text-terminal-dim font-mono">
            {item.task_id.slice(0, 8)}
          </p>
        </div>
        <div className={`px-3 py-1 text-xs font-semibold border ${getStatusBg(item.status)} ${getStatusColor(item.status)}`}>
          {item.status.toUpperCase()}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="text-lg font-bold text-neon-green tabular-nums">
            {item.credentials_count}
          </p>
          <p className="mono-label">CREDENTIALS</p>
        </div>
        <div>
          <p className="text-lg font-bold text-terminal-light tabular-nums">
            {item.duration ? `${item.duration.toFixed(1)}s` : '--'}
          </p>
          <p className="mono-label">DURATION</p>
        </div>
        <div>
          <p className="text-xs text-terminal-muted">
            {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
          </p>
          <p className="mono-label">COMPLETED</p>
        </div>
      </div>

      <a
        href={`/scan/${item.task_id}`}
        className="mt-3 flex items-center justify-center space-x-2 text-xs text-neon-cyan
                   hover:text-neon-green transition-colors"
      >
        <span>VIEW DETAILS</span>
        <ExternalLink className="w-3 h-3" />
      </a>
    </div>
  )
}
