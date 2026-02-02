import { useMemo } from 'react'
import {
  Shield,
  AlertTriangle,
  Users,
  Activity,
  Target
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Legend
} from 'recharts'
import { clsx } from 'clsx'

interface VictimMetrics {
  victim_count: number
  victim_coverage: number
  avg_bandwidth_amplification: number
  max_bandwidth_amplification: number
  total_excess_bandwidth: number
  avg_pollution_rate: number
  max_pollution_rate: number
  total_spam_accepted: number
  total_valid_txs_dropped: number
  avg_connectivity_loss: number
  isolated_victims: number
  collateral_damage: number
  per_victim: Record<string, {
    bandwidth_amplification: number
    pollution_rate: number
    spam_accepted: number
    valid_dropped: number
    peers_lost: number
  }>
}

interface AttackInfo {
  type: string
  attacker_count: number
  victim_count: number
  victim_strategy: string | null
  victims: string[]
  params: Record<string, unknown>
  metadata: Record<string, unknown>
}

interface VictimVisualizerProps {
  attack?: AttackInfo
  victimMetrics?: VictimMetrics
}

export function VictimVisualizer({ attack, victimMetrics }: VictimVisualizerProps) {
  if (!attack || attack.type === 'none') {
    return (
      <div className="p-4 bg-gray-50 rounded-lg">
        <div className="flex items-center text-gray-500">
          <Shield className="w-5 h-5 mr-2" />
          <span>No attack scenario in this run</span>
        </div>
      </div>
    )
  }

  const victimData = useMemo(() => {
    if (!victimMetrics?.per_victim) return []

    return Object.entries(victimMetrics.per_victim)
      .slice(0, 10) // Show top 10 victims
      .map(([id, metrics]) => ({
        id: id.split('-').pop(), // Shorten ID for display
        ...metrics
      }))
  }, [victimMetrics])

  const impactRadarData = useMemo(() => {
    if (!victimMetrics) return []

    return [
      {
        metric: 'Bandwidth',
        value: Math.min(victimMetrics.avg_bandwidth_amplification * 20, 100)
      },
      {
        metric: 'Blobpool',
        value: victimMetrics.avg_pollution_rate * 100
      },
      {
        metric: 'Connectivity',
        value: victimMetrics.avg_connectivity_loss * 100
      },
      {
        metric: 'Coverage',
        value: victimMetrics.victim_coverage * 100
      },
      {
        metric: 'Collateral',
        value: victimMetrics.collateral_damage * 100
      }
    ]
  }, [victimMetrics])

  const attackTypeColors = {
    'spam_t1_1': 'text-orange-600 bg-orange-100',
    'spam_t1_2': 'text-red-600 bg-red-100',
    'withholding_t2_1': 'text-purple-600 bg-purple-100',
    'poisoning_t4_2': 'text-pink-600 bg-pink-100'
  }

  const attackTypeLabels = {
    'spam_t1_1': 'Spam (Valid Headers)',
    'spam_t1_2': 'Spam (Invalid Data)',
    'withholding_t2_1': 'Column Withholding',
    'poisoning_t4_2': 'Availability Poisoning'
  }

  return (
    <div className="space-y-6">
      {/* Attack Overview */}
      <div className="bg-white p-4 rounded-lg border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold flex items-center">
            <Target className="w-5 h-5 mr-2 text-red-500" />
            Attack Scenario
          </h3>
          <span className={clsx(
            'px-2 py-1 rounded text-sm font-medium',
            attackTypeColors[attack.type as keyof typeof attackTypeColors] || 'text-gray-600 bg-gray-100'
          )}>
            {attackTypeLabels[attack.type as keyof typeof attackTypeLabels] || attack.type}
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-sm text-gray-500">Attackers</p>
            <p className="text-xl font-semibold">{attack.attacker_count}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Victims</p>
            <p className="text-xl font-semibold">{attack.victim_count}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Strategy</p>
            <p className="text-sm font-medium">{attack.victim_strategy || 'N/A'}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Coverage</p>
            <p className="text-xl font-semibold">
              {victimMetrics ? `${(victimMetrics.victim_coverage * 100).toFixed(1)}%` : 'N/A'}
            </p>
          </div>
        </div>
      </div>

      {victimMetrics && (
        <>
          {/* Impact Summary */}
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <h3 className="text-lg font-semibold mb-4 flex items-center">
              <AlertTriangle className="w-5 h-5 mr-2 text-yellow-500" />
              Impact Summary
            </h3>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
              <div className="p-3 bg-red-50 rounded">
                <p className="text-sm text-gray-600">Bandwidth Amplification</p>
                <p className="text-xl font-semibold text-red-600">
                  {victimMetrics.avg_bandwidth_amplification.toFixed(2)}x
                </p>
                <p className="text-xs text-gray-500">
                  Max: {victimMetrics.max_bandwidth_amplification.toFixed(2)}x
                </p>
              </div>

              <div className="p-3 bg-orange-50 rounded">
                <p className="text-sm text-gray-600">Blobpool Pollution</p>
                <p className="text-xl font-semibold text-orange-600">
                  {(victimMetrics.avg_pollution_rate * 100).toFixed(1)}%
                </p>
                <p className="text-xs text-gray-500">
                  {victimMetrics.total_spam_accepted} spam txs
                </p>
              </div>

              <div className="p-3 bg-purple-50 rounded">
                <p className="text-sm text-gray-600">Connectivity Loss</p>
                <p className="text-xl font-semibold text-purple-600">
                  {(victimMetrics.avg_connectivity_loss * 100).toFixed(1)}%
                </p>
                <p className="text-xs text-gray-500">
                  {victimMetrics.isolated_victims} isolated
                </p>
              </div>

              <div className="p-3 bg-blue-50 rounded">
                <p className="text-sm text-gray-600">Valid TXs Dropped</p>
                <p className="text-xl font-semibold text-blue-600">
                  {victimMetrics.total_valid_txs_dropped}
                </p>
              </div>

              <div className="p-3 bg-yellow-50 rounded">
                <p className="text-sm text-gray-600">Collateral Damage</p>
                <p className="text-xl font-semibold text-yellow-600">
                  {(victimMetrics.collateral_damage * 100).toFixed(1)}%
                </p>
              </div>

              <div className="p-3 bg-green-50 rounded">
                <p className="text-sm text-gray-600">Excess Bandwidth</p>
                <p className="text-xl font-semibold text-green-600">
                  {(victimMetrics.total_excess_bandwidth / 1024 / 1024).toFixed(1)} MB
                </p>
              </div>
            </div>

            {/* Impact Radar Chart */}
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={impactRadarData}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="metric" />
                  <PolarRadiusAxis angle={90} domain={[0, 100]} />
                  <Radar
                    name="Impact"
                    dataKey="value"
                    stroke="#ef4444"
                    fill="#ef4444"
                    fillOpacity={0.3}
                  />
                  <Tooltip />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Per-Victim Metrics */}
          {victimData.length > 0 && (
            <div className="bg-white p-4 rounded-lg border border-gray-200">
              <h3 className="text-lg font-semibold mb-4 flex items-center">
                <Users className="w-5 h-5 mr-2 text-blue-500" />
                Per-Victim Impact
              </h3>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-2">Victim ID</th>
                      <th className="text-right py-2">Bandwidth ×</th>
                      <th className="text-right py-2">Pollution %</th>
                      <th className="text-right py-2">Spam Accepted</th>
                      <th className="text-right py-2">Valid Dropped</th>
                      <th className="text-right py-2">Peers Lost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {victimData.map((victim) => (
                      <tr key={victim.id} className="border-b hover:bg-gray-50">
                        <td className="py-2 font-mono">{victim.id}</td>
                        <td className="text-right py-2">
                          <span className={clsx(
                            victim.bandwidth_amplification > 2 ? 'text-red-600 font-semibold' : ''
                          )}>
                            {victim.bandwidth_amplification.toFixed(2)}
                          </span>
                        </td>
                        <td className="text-right py-2">
                          {(victim.pollution_rate * 100).toFixed(1)}
                        </td>
                        <td className="text-right py-2">{victim.spam_accepted}</td>
                        <td className="text-right py-2">{victim.valid_dropped}</td>
                        <td className="text-right py-2">{victim.peers_lost}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Victim Impact Bar Chart */}
              <div className="mt-6 h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={victimData}>
                    <XAxis dataKey="id" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar
                      dataKey="bandwidth_amplification"
                      name="Bandwidth ×"
                      fill="#ef4444"
                    />
                    <Bar
                      dataKey="pollution_rate"
                      name="Pollution Rate"
                      fill="#f97316"
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}

      {/* Attack Parameters */}
      {attack.params && Object.keys(attack.params).length > 0 && (
        <div className="bg-white p-4 rounded-lg border border-gray-200">
          <h3 className="text-lg font-semibold mb-4 flex items-center">
            <Activity className="w-5 h-5 mr-2 text-green-500" />
            Attack Parameters
          </h3>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(attack.params).map(([key, value]) => (
              <div key={key} className="p-2 bg-gray-50 rounded">
                <p className="text-xs text-gray-500">{key.replace(/_/g, ' ')}</p>
                <p className="text-sm font-medium">
                  {typeof value === 'number'
                    ? value.toFixed(2)
                    : String(value)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}