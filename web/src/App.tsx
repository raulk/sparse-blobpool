import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  Activity,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  X,
  Hash,
  FileText,
  BarChart3,
  Terminal
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell
} from 'recharts'
import { clsx } from 'clsx'

const API_BASE = ''

interface RunSummary {
  run_id: string
  seed: number
  status: string
  anomalies: string[]
  wall_clock_seconds: number
  simulated_seconds: number
  timestamp: string
  metrics: Record<string, unknown>
}

interface RunDetails {
  run_id: string
  seed: number
  status: string
  anomalies: string[]
  wall_clock_seconds: number
  simulated_seconds: number
  timestamp_start: string
  timestamp_end: string
  metrics: Record<string, unknown>
  config?: Record<string, unknown>
  trace_config?: Record<string, unknown>
  trace_metrics?: Record<string, unknown>
  error?: string
}

interface DashboardStats {
  total_runs: number
  success_rate: number
  attention_rate: number
  error_rate: number
  runs_per_minute: number
  anomaly_distribution: Record<string, number>
  recent_runs: RunSummary[]
}

function App() {
  const queryClient = useQueryClient()
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [drawerTab, setDrawerTab] = useState<'params' | 'metrics' | 'logs'>('params')

  const { data: stats, isLoading } = useQuery<DashboardStats>({
    queryKey: ['stats'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/stats`)
      return res.json()
    },
    refetchInterval: 2000
  })

  const { data: runDetails, isLoading: isLoadingDetails } = useQuery<RunDetails>({
    queryKey: ['run', selectedRunId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/run/${selectedRunId}`)
      return res.json()
    },
    enabled: !!selectedRunId
  })

  useEffect(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`)

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'new_run') {
        queryClient.invalidateQueries({ queryKey: ['stats'] })
      }
    }

    return () => ws.close()
  }, [queryClient])

  if (isLoading || !stats) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <RefreshCw className="w-5 h-5 animate-spin text-slate-400" />
      </div>
    )
  }

  const statusData = [
    { name: 'Success', value: stats.success_rate * 100, color: '#22c55e' },
    { name: 'Flagged', value: stats.attention_rate * 100, color: '#eab308' },
    { name: 'Error', value: stats.error_rate * 100, color: '#ef4444' }
  ].filter(d => d.value > 0)

  const anomalyData = Object.entries(stats.anomaly_distribution)
    .map(([name, count]) => ({ name: name.length > 12 ? name.slice(0, 12) + '…' : name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5)

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 h-12 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-slate-600" />
            <span className="font-semibold text-slate-900">Fuzzer Monitor</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <span className="font-mono">{new Date().toLocaleTimeString()}</span>
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 bg-green-500 rounded-full pulse" />
              <span>Live</span>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-4">
        {/* Stats Row */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          <StatCard label="Total Runs" value={stats.total_runs.toLocaleString()} />
          <StatCard label="Runs/Min" value={stats.runs_per_minute.toFixed(1)} />
          <StatCard
            label="Success"
            value={`${(stats.success_rate * 100).toFixed(1)}%`}
            valueColor="text-green-600"
          />
          <StatCard
            label="Flagged"
            value={`${(stats.attention_rate * 100).toFixed(1)}%`}
            valueColor={stats.attention_rate > 0 ? 'text-amber-600' : undefined}
          />
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div className="bg-white border border-slate-200 rounded-lg p-4">
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-3">Status Distribution</h3>
            {statusData.length > 0 ? (
              <div className="flex items-center gap-4">
                <ResponsiveContainer width={100} height={100}>
                  <PieChart>
                    <Pie
                      data={statusData}
                      cx="50%"
                      cy="50%"
                      innerRadius={25}
                      outerRadius={45}
                      dataKey="value"
                      strokeWidth={0}
                    >
                      {statusData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex flex-col gap-1.5">
                  {statusData.map((item) => (
                    <div key={item.name} className="flex items-center gap-2 text-xs">
                      <div className="w-2 h-2 rounded-sm" style={{ backgroundColor: item.color }} />
                      <span className="text-slate-600">{item.name}</span>
                      <span className="font-mono text-slate-900">{item.value.toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-[100px] flex items-center justify-center text-xs text-slate-400">
                No data yet
              </div>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-lg p-4">
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-3">Top Anomalies</h3>
            {anomalyData.length > 0 ? (
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={anomalyData} layout="vertical" margin={{ left: 0, right: 0 }}>
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={80}
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    contentStyle={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4 }}
                  />
                  <Bar dataKey="count" fill="#6366f1" radius={2} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[100px] flex items-center justify-center text-xs text-slate-400">
                No anomalies detected
              </div>
            )}
          </div>
        </div>

        {/* Runs Table */}
        <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
          <div className="px-4 py-2.5 border-b border-slate-200 flex items-center justify-between">
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wide">Recent Runs</h3>
            <span className="text-xs text-slate-400">{stats.recent_runs.length} runs</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-left text-xs text-slate-500 uppercase tracking-wide">
                  <th className="px-4 py-2 font-medium">Run ID</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Seed</th>
                  <th className="px-4 py-2 font-medium">Duration</th>
                  <th className="px-4 py-2 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {stats.recent_runs.map((run) => (
                  <tr
                    key={run.run_id}
                    className={clsx(
                      'hover:bg-slate-50 cursor-pointer transition-colors',
                      selectedRunId === run.run_id && 'bg-blue-50'
                    )}
                    onClick={() => {
                      setSelectedRunId(run.run_id)
                      setDrawerTab('params')
                    }}
                  >
                    <td className="px-4 py-2">
                      <span className="font-mono text-xs text-slate-700">{run.run_id}</span>
                    </td>
                    <td className="px-4 py-2">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-2">
                      <span className="font-mono text-xs text-slate-500">{run.seed}</span>
                    </td>
                    <td className="px-4 py-2">
                      <span className="font-mono text-xs text-slate-500">{run.wall_clock_seconds.toFixed(2)}s</span>
                    </td>
                    <td className="px-4 py-2">
                      <span className="text-xs text-slate-500">
                        {new Date(run.timestamp).toLocaleTimeString()}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {stats.recent_runs.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-slate-400">
                No runs yet. Start the fuzzer to see results.
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Run Details Drawer */}
      {selectedRunId && (
        <>
          <div
            className="fixed inset-0 bg-black/20 z-20"
            onClick={() => setSelectedRunId(null)}
          />
          <div className="fixed right-0 top-0 bottom-0 w-[480px] bg-white border-l border-slate-200 z-30 drawer-enter flex flex-col">
            {/* Drawer Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
              <div className="flex items-center gap-2">
                <Hash className="w-4 h-4 text-slate-400" />
                <span className="font-mono text-sm font-medium">{selectedRunId}</span>
              </div>
              <button
                onClick={() => setSelectedRunId(null)}
                className="p-1 hover:bg-slate-100 rounded"
              >
                <X className="w-4 h-4 text-slate-400" />
              </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-slate-200">
              <TabButton
                active={drawerTab === 'params'}
                onClick={() => setDrawerTab('params')}
                icon={<FileText className="w-3.5 h-3.5" />}
                label="Parameters"
              />
              <TabButton
                active={drawerTab === 'metrics'}
                onClick={() => setDrawerTab('metrics')}
                icon={<BarChart3 className="w-3.5 h-3.5" />}
                label="Metrics"
              />
              <TabButton
                active={drawerTab === 'logs'}
                onClick={() => setDrawerTab('logs')}
                icon={<Terminal className="w-3.5 h-3.5" />}
                label="Logs"
              />
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto p-4">
              {isLoadingDetails ? (
                <div className="flex items-center justify-center py-8">
                  <RefreshCw className="w-4 h-4 animate-spin text-slate-400" />
                </div>
              ) : runDetails?.error ? (
                <div className="text-sm text-red-600 bg-red-50 rounded p-3">
                  {runDetails.error}
                </div>
              ) : runDetails ? (
                <>
                  {drawerTab === 'params' && (
                    <div className="space-y-4">
                      <Section title="Run Info">
                        <InfoRow label="Status">
                          <StatusBadge status={runDetails.status} />
                        </InfoRow>
                        <InfoRow label="Seed">
                          <span className="font-mono">{runDetails.seed}</span>
                        </InfoRow>
                        <InfoRow label="Started">
                          {new Date(runDetails.timestamp_start).toLocaleString()}
                        </InfoRow>
                        <InfoRow label="Ended">
                          {new Date(runDetails.timestamp_end).toLocaleString()}
                        </InfoRow>
                        <InfoRow label="Wall Clock">
                          <span className="font-mono">{runDetails.wall_clock_seconds.toFixed(3)}s</span>
                        </InfoRow>
                        <InfoRow label="Simulated Time">
                          <span className="font-mono">{runDetails.simulated_seconds.toFixed(1)}s</span>
                        </InfoRow>
                      </Section>

                      {runDetails.anomalies && runDetails.anomalies.length > 0 && (
                        <Section title="Anomalies">
                          <div className="space-y-1">
                            {runDetails.anomalies.map((anomaly, i) => (
                              <div key={i} className="text-xs font-mono text-amber-700 bg-amber-50 px-2 py-1 rounded">
                                {anomaly}
                              </div>
                            ))}
                          </div>
                        </Section>
                      )}

                      <ConfigDisplay config={runDetails.trace_config || runDetails.config} />
                    </div>
                  )}

                  {drawerTab === 'metrics' && (
                    <MetricsDisplay metrics={runDetails.trace_metrics || runDetails.metrics} />
                  )}

                  {drawerTab === 'logs' && (
                    <div className="space-y-4">
                      <div className="text-xs text-slate-500 bg-slate-50 rounded p-3">
                        Logs are available for flagged runs with trace files.
                        <br />
                        Run with <code className="bg-slate-200 px-1 rounded">--trace-all</code> to capture all logs.
                      </div>
                      {runDetails.trace_config && (
                        <div className="text-xs text-slate-400">
                          Trace directory: <code className="font-mono">fuzzer_output/{runDetails.run_id}/</code>
                        </div>
                      )}
                    </div>
                  )}
                </>
              ) : null}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function StatCard({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg px-4 py-3">
      <div className="text-xs text-slate-500 mb-0.5">{label}</div>
      <div className={clsx('text-xl font-semibold font-mono', valueColor || 'text-slate-900')}>
        {value}
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'success') {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-1.5 py-0.5 rounded">
        <CheckCircle className="w-3 h-3" />
        Success
      </span>
    )
  }

  if (status.includes('ATTENTION')) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
        <AlertCircle className="w-3 h-3" />
        Flagged
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1 text-xs text-red-700 bg-red-50 px-1.5 py-0.5 rounded">
      <AlertCircle className="w-3 h-3" />
      Error
    </span>
  )
}

function TabButton({
  active,
  onClick,
  icon,
  label
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors',
        active
          ? 'text-blue-600 border-b-2 border-blue-600 -mb-px'
          : 'text-slate-500 hover:text-slate-700'
      )}
    >
      {icon}
      {label}
    </button>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">{title}</h4>
      {children}
    </div>
  )
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs text-slate-900">{children}</span>
    </div>
  )
}

function ConfigDisplay({ config }: { config?: Record<string, unknown> }) {
  if (!config) {
    return (
      <div className="text-sm text-slate-400 text-center py-4">
        No configuration data available.
      </div>
    )
  }

  const networkParams = ['node_count', 'mesh_degree', 'interconnection_policy', 'default_bandwidth']
  const protocolParams = ['custody_columns', 'extra_random_columns', 'max_columns_per_request', 'min_providers_before_sample', 'provider_probability']
  const timingParams = ['slot_duration', 'duration', 'provider_observation_timeout', 'request_timeout', 'tx_expiration']
  const blobpoolParams = ['blobpool_max_bytes', 'max_txs_per_sender', 'max_blobs_per_block', 'inclusion_policy']
  const otherParams = ['scenario', 'seed']

  const getParamsFromConfig = (keys: string[]) =>
    keys.filter(k => k in config).map(k => ({ key: k, value: config[k] }))

  const formatValue = (key: string, value: unknown): string => {
    if (value === null || value === undefined) return '—'
    if (typeof value === 'boolean') return value ? 'Yes' : 'No'
    if (typeof value === 'number') {
      if (key.includes('bytes') || key.includes('bandwidth')) {
        return formatBytes(value)
      }
      if (key.includes('timeout') || key.includes('duration') || key.includes('expiration')) {
        return `${value.toFixed(1)}s`
      }
      if (key.includes('probability') || key.includes('ratio') || key.includes('rate')) {
        return `${(value * 100).toFixed(1)}%`
      }
      if (Number.isInteger(value)) return value.toLocaleString()
      return value.toFixed(3)
    }
    if (typeof value === 'string') {
      return value.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
    }
    return String(value)
  }

  const formatLabel = (key: string): string => {
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase())
      .replace('Txs', 'TXs')
      .replace('Tx ', 'TX ')
  }

  const ParamGroup = ({ title, params }: { title: string; params: { key: string; value: unknown }[] }) => {
    if (params.length === 0) return null
    return (
      <Section title={title}>
        {params.map(({ key, value }) => (
          <InfoRow key={key} label={formatLabel(key)}>
            <span className="font-mono">{formatValue(key, value)}</span>
          </InfoRow>
        ))}
      </Section>
    )
  }

  return (
    <div className="space-y-4">
      <ParamGroup title="Network" params={getParamsFromConfig(networkParams)} />
      <ParamGroup title="Protocol" params={getParamsFromConfig(protocolParams)} />
      <ParamGroup title="Timing" params={getParamsFromConfig(timingParams)} />
      <ParamGroup title="Blobpool" params={getParamsFromConfig(blobpoolParams)} />
      <ParamGroup title="Other" params={getParamsFromConfig(otherParams)} />
    </div>
  )
}

function MetricsDisplay({ metrics }: { metrics?: Record<string, unknown> }) {
  if (!metrics || Object.keys(metrics).length === 0) {
    return (
      <div className="text-sm text-slate-400 text-center py-8">
        No metrics available for this run.
      </div>
    )
  }

  const bandwidthMetrics = ['total_bandwidth_bytes', 'bandwidth_per_blob', 'bandwidth_reduction_vs_full']
  const propagationMetrics = ['median_propagation_time', 'p99_propagation_time', 'propagation_success_rate']
  const providerMetrics = ['observed_provider_ratio', 'provider_coverage', 'expected_provider_coverage']
  const availabilityMetrics = ['reconstruction_success_rate', 'false_availability_rate', 'local_availability_met']
  const attackMetrics = ['spam_amplification_factor', 'victim_blobpool_pollution', 'withholding_detection_rate']

  const getMetricsFromData = (keys: string[]) =>
    keys.filter(k => k in metrics).map(k => ({ key: k, value: metrics[k] as number }))

  const formatValue = (key: string, value: number): string => {
    if (key.includes('bytes') || key.includes('bandwidth')) {
      if (key === 'bandwidth_reduction_vs_full') return `${value.toFixed(2)}x`
      return formatBytes(value)
    }
    if (key.includes('time')) {
      return value === 0 ? '—' : `${value.toFixed(2)}s`
    }
    if (key.includes('rate') || key.includes('ratio') || key.includes('coverage') || key.includes('met') || key.includes('factor') || key.includes('pollution')) {
      const pct = value * 100
      return `${pct.toFixed(1)}%`
    }
    return value.toFixed(3)
  }

  const formatLabel = (key: string): string => {
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase())
      .replace('P99', 'P99')
      .replace('Vs', 'vs')
  }

  const getStatusColor = (key: string, value: number): string | undefined => {
    if (key === 'reconstruction_success_rate' || key === 'local_availability_met') {
      return value >= 0.99 ? 'text-green-600' : value >= 0.9 ? 'text-amber-600' : 'text-red-600'
    }
    if (key === 'false_availability_rate' || key === 'spam_amplification_factor' || key === 'victim_blobpool_pollution') {
      return value === 0 ? 'text-green-600' : value < 0.1 ? 'text-amber-600' : 'text-red-600'
    }
    if (key === 'bandwidth_reduction_vs_full') {
      return value >= 3 ? 'text-green-600' : value >= 2 ? 'text-slate-600' : 'text-amber-600'
    }
    return undefined
  }

  const MetricGroup = ({ title, items }: { title: string; items: { key: string; value: number }[] }) => {
    if (items.length === 0) return null
    return (
      <Section title={title}>
        {items.map(({ key, value }) => (
          <InfoRow key={key} label={formatLabel(key)}>
            <span className={clsx('font-mono', getStatusColor(key, value))}>
              {formatValue(key, value)}
            </span>
          </InfoRow>
        ))}
      </Section>
    )
  }

  return (
    <div className="space-y-4">
      <MetricGroup title="Bandwidth" items={getMetricsFromData(bandwidthMetrics)} />
      <MetricGroup title="Propagation" items={getMetricsFromData(propagationMetrics)} />
      <MetricGroup title="Provider Coverage" items={getMetricsFromData(providerMetrics)} />
      <MetricGroup title="Availability" items={getMetricsFromData(availabilityMetrics)} />
      <MetricGroup title="Attack Resilience" items={getMetricsFromData(attackMetrics)} />
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

export default App
