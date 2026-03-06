export interface Credential {
  type: string
  confidence: number
  file_path: string
  layer_id?: string
  line_number?: number
  validation_status?: string
  context?: string
}

export interface ScanStatistics {
  total_layers: number
  processed_layers: number
  total_files: number
  scanned_files: number
}

export interface ScanResult {
  task_id: string
  image_name: string
  status: 'running' | 'completed' | 'failed'
  credentials: Credential[]
  statistics?: ScanStatistics
  token_usage?: Record<string, number>
  duration?: number
  started_at?: string
  completed_at?: string
}

export interface ScanEvent {
  type: string
  source: string
  data?: Record<string, any>
  timestamp: string
}
