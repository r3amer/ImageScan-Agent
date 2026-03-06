'use client'

import { ScanEvent } from '@/types/scan'
import { Terminal, AlertCircle, CheckCircle, XCircle, Info } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

interface EventLogProps {
  events: ScanEvent[]
}

export default function EventLog({ events }: EventLogProps) {
  const getEventIcon = (type: string) => {
    if (type.includes('error')) {
      return <XCircle className="w-3.5 h-3.5 text-neon-red" />
    }
    if (type.includes('system.connected') || type.includes('completed')) {
      return <CheckCircle className="w-3.5 h-3.5 text-neon-green" />
    }
    if (type.includes('started') || type.includes('progress')) {
      return <Terminal className="w-3.5 h-3.5 text-neon-cyan" />
    }
    return <Info className="w-3.5 h-3.5 text-terminal-dim" />
  }

  const getEventColor = (type: string) => {
    if (type.includes('error')) return 'text-neon-red'
    if (type.includes('system.connected') || type.includes('completed')) return 'text-neon-green'
    if (type.includes('started') || type.includes('progress')) return 'text-neon-cyan'
    return 'text-terminal-light/70'
  }

  return (
    <div className="data-card h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-terminal-muted">
        <div className="flex items-center space-x-2">
          <Terminal className="w-4 h-4 text-neon-green" />
          <span className="text-xs font-mono text-neon-green">EVENT LOG</span>
        </div>
      </div>

      {/* Events list */}
      <div className="flex-1 overflow-y-auto space-y-1.5 min-h-[500px] max-h-[600px]">
        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-terminal-dim py-12">
            <Terminal className="w-8 h-8 mb-3 opacity-40" />
            <p className="text-xs">No events yet</p>
          </div>
        ) : (
          events.map((event, idx) => (
            <div
              key={`${event.timestamp}-${idx}`}
              className="bg-terminal-dark/40 border border-terminal-muted p-2.5 text-sm hover:border-terminal-light/20 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center space-x-2 flex-1 min-w-0">
                  {getEventIcon(event.type)}
                  <span className={`font-mono text-[10px] uppercase tracking-wider ${getEventColor(event.type)}`}>
                    {event.type.replace(/\./g, '_')}
                  </span>
                </div>
                <span className="text-[10px] text-terminal-dim whitespace-nowrap ml-2 font-mono">
                  {formatDistanceToNow(new Date(event.timestamp), { addSuffix: true })}
                </span>
              </div>

              {/* Event message */}
              {event.data?.message && (
                <p className={`text-[11px] mt-1.5 ml-5 font-mono ${
                  event.type === 'error' ? 'text-neon-red' : 'text-terminal-muted'
                }`}>
                  {event.data.message}
                </p>
              )}

              {/* Credential found */}
              {event.data?.credential && (
                <div className="mt-2 ml-5 p-2 bg-terminal-black/60 border border-terminal-light/20">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] text-neon-orange font-mono uppercase">
                      {event.data.credential.type}
                    </span>
                    <span className="text-[10px] text-neon-green font-mono">
                      {Math.round(event.data.credential.confidence * 100)}%
                    </span>
                  </div>
                  <p className="text-[10px] text-terminal-dim font-mono truncate">
                    {event.data.credential.file_path}
                  </p>
                </div>
              )}

              {/* Statistics */}
              {event.data?.statistics && (
                <div className="mt-2 ml-5 text-[10px] text-terminal-dim font-mono">
                  <span className="text-neon-cyan">
                    {event.data.statistics.processed_layers}/{event.data.statistics.total_layers}
                  </span>
                  {' '}
                  <span className="text-terminal-light/20">•</span>
                  {' '}
                  <span className="text-neon-green">
                    {event.data.statistics.scanned_files}
                  </span>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="pt-3 mt-3 border-t border-terminal-muted text-[10px] text-terminal-dim font-mono">
        {events.length} event{events.length !== 1 ? 's' : ''}
      </div>
    </div>
  )
}
