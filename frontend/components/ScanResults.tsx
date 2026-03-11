'use client'

import { ScanResult } from '@/types/scan'
import { CheckCircle, AlertTriangle, Shield, FileText, Calendar, Clock } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

interface ScanResultsProps {
  result: ScanResult
}

export default function ScanResults({ result }: ScanResultsProps) {
  const hasCredentials = result.credentials.length > 0
  const highRiskCount = result.credentials.filter(c => c.confidence > 0.8).length

  return (
    <div className="data-card border-neon-green">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-3">
          <CheckCircle className="w-6 h-6 text-neon-green" />
          <div>
            <h2 className="text-lg font-bold text-neon-green">SCAN COMPLETE</h2>
            <p className="mono-label">{result.image_name}</p>
          </div>
        </div>
        {hasCredentials && (
          <div className="px-3 py-1 bg-neon-orange/10 border border-neon-orange text-neon-orange text-sm font-semibold">
            {highRiskCount} HIGH RISK
          </div>
        )}
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
          <Shield className="w-5 h-5 text-neon-green mb-2" />
          <div className="text-2xl font-bold text-neon-green tabular-nums">
            {result.credentials.length}
          </div>
          <p className="mono-label mt-1">TOTAL CREDENTIALS</p>
        </div>

        <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
          <AlertTriangle className="w-5 h-5 text-neon-orange mb-2" />
          <div className="text-2xl font-bold text-neon-orange tabular-nums">
            {highRiskCount}
          </div>
          <p className="mono-label mt-1">HIGH RISK</p>
        </div>

        {result.statistics && (
          <>
            <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
              <FileText className="w-5 h-5 text-neon-cyan mb-2" />
              <div className="text-2xl font-bold text-neon-cyan tabular-nums">
                {result.statistics.scanned_files}
              </div>
              <p className="mono-label mt-1">FILES SCANNED</p>
            </div>

            <div className="bg-terminal-black/50 p-4 border border-terminal-muted">
              <Clock className="w-5 h-5 text-terminal-light mb-2" />
              <div className="text-2xl font-bold text-terminal-light tabular-nums">
                {result.duration ? `${result.duration.toFixed(1)}s` : '--'}
              </div>
              <p className="mono-label mt-1">DURATION</p>
            </div>
          </>
        )}
      </div>

      {/* Credentials list */}
      {hasCredentials ? (
        <div>
          <p className="mono-label mb-3">DISCOVERED CREDENTIALS</p>
          <div className="space-y-3">
            {result.credentials.map((cred, idx) => (
              <CredentialCard key={idx} credential={cred} index={idx} />
            ))}
          </div>
        </div>
      ) : (
        <div className="bg-terminal-black/50 border border-neon-green/30 p-8 text-center">
          <Shield className="w-12 h-12 text-neon-green mx-auto mb-4" />
          <h3 className="text-neon-green font-bold mb-2">NO CREDENTIALS FOUND</h3>
          <p className="text-terminal-muted text-sm">
            The scan completed successfully but no exposed credentials were detected.
          </p>
        </div>
      )}

      {/* Metadata */}
      {result.completed_at && (
        <div className="mt-6 pt-6 border-t border-terminal-muted text-xs text-terminal-muted">
          <div className="flex items-center space-x-2">
            <Calendar className="w-4 h-4" />
            <span>
              Completed{' '}
              {formatDistanceToNow(new Date(result.completed_at), { addSuffix: true })}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function CredentialCard({ credential, index }: { credential: any; index: number }) {
  const isHighRisk = credential.confidence > 0.8
  const typeCategory = credential.type.split('_')[0]

  return (
    <div className={`bg-terminal-black/50 border p-4 ${
      isHighRisk ? 'border-neon-orange' : 'border-terminal-muted'
    }`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center space-x-3">
          <span className="text-terminal-dim font-mono text-sm">
            #{String(index + 1).padStart(3, '0')}
          </span>
          <span className={`credential-tag credential-tag-${typeCategory}`}>
            {credential.type}
          </span>
          {isHighRisk && (
            <span className="px-2 py-1 text-xs bg-neon-orange/10 border border-neon-orange text-neon-orange">
              HIGH RISK
            </span>
          )}
        </div>
        <div className="text-right">
          <div className={`text-lg font-bold tabular-nums ${
            isHighRisk ? 'text-neon-orange' : 'text-neon-green'
          }`}>
            {Math.round(credential.confidence * 100)}%
          </div>
          <p className="mono-label">CONFIDENCE</p>
        </div>
      </div>

      {/* File path */}
      <div className="mb-2">
        <p className="mono-label mb-1">LOCATION</p>
        <p className="text-sm text-terminal-light font-mono break-all">
          {credential.file_path}
        </p>
      </div>

      {/* Additional metadata */}
      {(credential.line_number || credential.layer_id) && (
        <div className="flex items-center space-x-4 text-xs text-terminal-muted">
          {credential.line_number && (
            <span>Line: {credential.line_number}</span>
          )}
          {credential.layer_id && (
            <span className="font-mono">
              Layer: {credential.layer_id.slice(0, 12)}
            </span>
          )}
        </div>
      )}

      {/* Context preview */}
      {credential.context && (
        <div className="mt-3 pt-3 border-t border-terminal-light/20">
          <p className="mono-label mb-1">CONTEXT</p>
          <pre className="text-xs text-terminal-light/70 bg-terminal-dark p-2 overflow-x-auto">
            {credential.context}
          </pre>
        </div>
      )}
    </div>
  )
}
