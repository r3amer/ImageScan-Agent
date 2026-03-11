'use client'

import { useState } from 'react'
import ScanInterface from '@/components/ScanInterface'

export default function Home() {
  const [sessionId] = useState(() => {
    if (typeof window !== 'undefined') {
      return sessionStorage.getItem('scan_session') || `session_${Date.now()}`
    }
    return `session_${Date.now()}`
  })

  return (
    <main className="min-h-screen relative scanlines">
      {/* Background grid pattern */}
      <div
        className="fixed inset-0 opacity-10 pointer-events-none"
        style={{
          backgroundImage: `
            linear-gradient(to right, #1a1a1a 1px, transparent 1px),
            linear-gradient(to bottom, #1a1a1a 1px, transparent 1px)
          `,
          backgroundSize: '50px 50px'
        }}
      />

      {/* Main content */}
      <div className="relative z-0">
        {/* Header */}
        <header className="border-b-2 border-terminal-light bg-terminal-dark/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center space-x-3">
                <div className="w-8 h-8 border-2 border-neon-green flex items-center justify-center">
                  <span className="text-neon-green text-lg font-bold">&gt;</span>
                </div>
                <div>
                  <h1 className="text-xl font-bold text-neon-green glow-green">ImageScan</h1>
                  <p className="text-xs text-terminal-light/60">Container Security Scanner</p>
                </div>
              </div>

              <div className="flex items-center space-x-4 text-xs font-mono">
                <div className="hidden sm:flex items-center space-x-2 text-terminal-light/60">
                  <span className="status-dot bg-neon-green"></span>
                  <span>SYSTEM ONLINE</span>
                </div>
                <div className="px-3 py-1 border border-terminal-light/30 bg-terminal-black/50">
                  v0.1.0
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* Main interface */}
        <ScanInterface sessionId={sessionId} />
      </div>
    </main>
  )
}
