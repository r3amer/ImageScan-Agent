'use client'

import { ScanResult } from '@/types/scan'
import { ScanEvent } from '@/types/scan'
import { Layers, FileText, Shield, AlertTriangle, Clock } from 'lucide-react'

interface ScanProgressProps {
  result: ScanResult
  events: ScanEvent[]
}

export default function ScanProgress({ result, events }: ScanProgressProps) {
  const isRunning = result.status === 'running'
  const stats = result.statistics

  // Calculate progress percentage
  const progress = stats && stats.total_layers > 0
    ? Math.round((stats.processed_layers / stats.total_layers) * 100)
    : 0

  // Get latest relevant event
  const latestEvent = events.find(e =>
    e.type === 'layer.completed' ||
    e.type === 'file.scanned' ||
    e.type === 'credential.found'
  )

  return (
    <div className="data-card border-neon-green/30">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-3">
          <Shield className="w-6 h-6 text-neon-green" />
          <div>
            <h2 className="text-lg font-bold text-neon-green">SCAN IN PROGRESS</h2>
            <p className="mono-label">{result.image_name}</p>
          </div>
        </div>
        {isRunning && (
          <div className="flex items-center space-x-2 text-neon-green text-sm">
            <span className="w-2 h-2 bg-neon-green rounded-full animate-pulse" />
            <span className="animate-pulse">ACTIVE</span>
          </div>
        )}
      </div>

      {/* Progress bar */}
      {stats && stats.total_layers > 0 && (
        <div className="mb-6">
          <div className="flex justify-between text-xs mb-2">
            <span className="text-terminal-muted">PROGRESS</span>
            <span className="text-neon-green font-mono">{progress}%</span>
          </div>
          <div className="terminal-progress">
            <div
              className="terminal-progress-bar"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Stats grid */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
            <Layers className="w-5 h-5 text-neon-cyan mb-2" />
            <div className="text-2xl font-bold text-neon-cyan tabular-nums">
              {stats.processed_layers}/{stats.total_layers}
            </div>
            <p className="mono-label mt-1">LAYERS</p>
          </div>

          <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
            <FileText className="w-5 h-5 text-neon-green mb-2" />
            <div className="text-2xl font-bold text-neon-green tabular-nums">
              {stats.scanned_files}
            </div>
            <p className="mono-label mt-1">FILES SCANNED</p>
          </div>

          <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
            <AlertTriangle className="w-5 h-5 text-neon-orange mb-2" />
            <div className="text-2xl font-bold text-neon-orange tabular-nums">
              {result.credentials.length}
            </div>
            <p className="mono-label mt-1">CREDENTIALS FOUND</p>
          </div>

          <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
            <Clock className="w-5 h-5 text-terminal-light mb-2" />
            <div className="text-2xl font-bold text-terminal-light tabular-nums">
              {result.duration ? `${result.duration.toFixed(1)}s` : '--'}
            </div>
            <p className="mono-label mt-1">DURATION</p>
          </div>
        </div>
      )}

      {/* Current activity */}
      {isRunning && latestEvent && (
        <div className="bg-terminal-black/50 border border-terminal-muted p-4">
          <p className="mono-label mb-2">CURRENT ACTIVITY</p>
          <div className="flex items-center space-x-2 text-sm">
            <span className="text-neon-cyan animate-pulse">▶</span>
            <p className="text-terminal-light">
              {latestEvent.data?.message || latestEvent.type.replace(/\./g, ' ').toUpperCase()}
            </p>
          </div>
        </div>
      )}

      {/* Credentials preview */}
      {result.credentials.length > 0 && (
        <div className="mt-6 pt-6 border-t border-terminal-muted">
          <p className="mono-label mb-3">DISCOVERED CREDENTIALS</p>
          <div className="space-y-2">
            {result.credentials.slice(0, 3).map((cred, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between bg-terminal-black/50 border border-terminal-muted p-3"
              >
                <div className="flex items-center space-x-3">
                  <span className={`credential-tag credential-tag-${cred.type.split('_')[0]}`}>
                    {cred.type}
                  </span>
                  <span className="text-sm text-terminal-light/80 font-mono">
                    {cred.file_path}
                  </span>
                </div>
                <span className="text-xs text-neon-green font-mono">
                  {Math.round(cred.confidence * 100)}%
                </span>
              </div>
            ))}
            {result.credentials.length > 3 && (
              <p className="text-xs text-terminal-muted text-center">
                +{result.credentials.length - 3} more credentials
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
