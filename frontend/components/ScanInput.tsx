'use client'

import { useState, FormEvent } from 'react'
import { Terminal, Container } from 'lucide-react'

interface ScanInputProps {
  onStartScan: (imageName: string) => void
  isScanning: boolean
}

export default function ScanInput({ onStartScan, isScanning }: ScanInputProps) {
  const [imageName, setImageName] = useState('')
  const [isValid, setIsValid] = useState(true)

  const validateImageName = (name: string) => {
    // Basic validation for Docker image names
    const dockerImageRegex = /^([\w\.\-]+(:[0-9]+)?\/)?([\w\.\-]+\/)*[\w\.\-]+(:[\w\.\-]+)?$/
    return dockerImageRegex.test(name.trim())
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()

    if (!imageName.trim()) {
      setIsValid(false)
      return
    }

    if (!validateImageName(imageName)) {
      setIsValid(false)
      return
    }

    setIsValid(true)
    onStartScan(imageName.trim())
  }

  const handleInputChange = (value: string) => {
    setImageName(value)
    if (value.trim() && !validateImageName(value)) {
      setIsValid(false)
    } else {
      setIsValid(true)
    }
  }

  const exampleImages = [
    'nginx:latest',
    'python:3.11-slim',
    'node:20-alpine',
    'postgres:15',
  ]

  return (
    <div className="data-card">
      {/* Header */}
      <div className="flex items-center space-x-3 mb-6">
        <Container className="w-6 h-6 text-neon-green" />
        <div>
          <h2 className="text-lg font-bold text-neon-green">SCAN IMAGE</h2>
          <p className="mono-label">Enter Docker image name or ID</p>
        </div>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="relative">
          <div className="absolute left-4 top-1/2 -translate-y-1/2 text-terminal-dim">
            <Terminal className="w-5 h-5" />
          </div>
          <input
            type="text"
            value={imageName}
            onChange={(e) => handleInputChange(e.target.value)}
            placeholder="nginx:latest"
            disabled={isScanning}
            className="terminal-input pl-12"
            autoComplete="off"
          />
        </div>

        {!isValid && (
          <p className="text-neon-red text-sm flex items-center space-x-2">
            <span className="animate-blink">⚠</span>
            <span>Invalid Docker image name format</span>
          </p>
        )}

        <div className="flex items-center space-x-3">
          <button
            type="submit"
            disabled={isScanning || !imageName.trim()}
            className="terminal-button-primary flex-1 flex items-center justify-center space-x-2"
          >
            {isScanning ? (
              <>
                <span className="w-4 h-4 border-2 border-current border-t-transparent animate-spin" />
                <span>SCANNING...</span>
              </>
            ) : (
              <>
                <Terminal className="w-4 h-4" />
                <span>START SCAN</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => {
              setImageName('')
              setIsValid(true)
            }}
            disabled={isScanning}
            className="terminal-button-secondary px-4"
          >
            CLEAR
          </button>
        </div>
      </form>

      {/* Example images */}
      <div className="mt-6 pt-6 border-t border-terminal-light">
        <p className="mono-label mb-3">QUICK EXAMPLES</p>
        <div className="flex flex-wrap gap-2">
          {exampleImages.map((example) => (
            <button
              key={example}
              onClick={() => handleInputChange(example)}
              disabled={isScanning}
              className="px-3 py-1 text-xs border border-terminal-muted bg-terminal-black/50
                         hover:border-neon-green hover:text-neon-green transition-all
                         font-mono disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {example}
            </button>
          ))}
        </div>
      </div>

      {/* Info box */}
      <div className="mt-6 p-4 bg-terminal-black/50 border border-terminal-muted">
        <p className="text-xs text-terminal-muted leading-relaxed">
          <span className="text-neon-cyan font-semibold">INFO:</span> The scanner will analyze
          the Docker image for exposed credentials, API keys, tokens, certificates,
          and other sensitive data using intelligent LLM-based detection.
        </p>
      </div>
    </div>
  )
}
