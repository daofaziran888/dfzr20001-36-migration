/** 跨模块流水线 API 客户端：批次追溯、工序推进、门禁检查。 */
import { fetchJson, request } from './client'

const API = '/api/pipeline'
const PAN_API = '/api/pan'

export interface PanProof {
  锅号: string
  有效证明: Record<string, any> | null
  告知来源: Record<string, any>[]
  核对: {
    锅号: string
    原旧凭据继续受理: boolean
    需要确认刚来的锅温日志: boolean
    实际采用: string | null
    实际采用证明ID: number | null
    说明: string
    告知来源数: number
  }
}

export type ReceivingPlan = PanProof & {
  揉捻记录ID?: number
  已接料?: Record<string, any> | null
}

export async function fetchReceivingPlan(rollingId: number): Promise<ReceivingPlan> {
  return fetchJson<ReceivingPlan>(`/api/rolling/${rollingId}/receiving-proof`)
}

export function emptyPlan(pot: string): PanProof & { 揉捻记录ID?: number; 已接料?: Record<string, any> | null } {
  return {
    锅号: pot,
    有效证明: null,
    告知来源: [],
    核对: {
      锅号: pot,
      原旧凭据继续受理: false,
      需要确认刚来的锅温日志: false,
      实际采用: null,
      实际采用证明ID: null,
      说明: '',
      告知来源数: 0,
    },
  }
}

export async function receiveRolling(rollingId: number): Promise<{ ok: boolean; message: string }> {
  const response = await request(`/api/rolling/${rollingId}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action: '完成接料' }),
  })
  const payload = await response.json()
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message || payload.detail || '接料失败')
  }
  return payload
}

export async function fetchReceiptHistory(rollingId: number): Promise<{ total: number; items: Record<string, any>[] }> {
  return fetchJson(`/api/pan/receipts/${rollingId}`)
}

export async function fetchPanProof(pot: string): Promise<PanProof> {
  return fetchJson<PanProof>(`${PAN_API}/proofs/${encodeURIComponent(pot)}`)
}

export async function fetchPendingReceiving(): Promise<{ total: number; items: Record<string, any>[] }> {
  return fetchJson(`${PAN_API}/pending-receiving`)
}

export async function fetchLegacyQuery(): Promise<{ total: number; items: Record<string, any>[] }> {
  return fetchJson(`${PAN_API}/legacy`)
}

export async function fetchPanLogs(pot: string): Promise<{ total: number; items: Record<string, any>[] }> {
  return fetchJson(`${PAN_API}/logs?pot=${encodeURIComponent(pot)}`)
}

export async function confirmPanLog(logId: number): Promise<{ ok: boolean; message: string; log: Record<string, any> }> {
  const response = await request(`${PAN_API}/logs/${logId}/confirm`, { method: 'POST' })
  const payload = await response.json()
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message || payload.detail || '确认锅温日志失败')
  }
  return payload
}

export async function fetchPanState(): Promise<{ mode: string; rollback_at: string | null; logs: number; legacy_logs: number; proofs: number; receipts: number }> {
  const payload = await fetchJson<{ state: any }>(`${PAN_API}/state`)
  return payload.state
}

export interface TraceNode {
  module: string
  entry_id: number
  data: Record<string, string | number>
}

export interface TraceChain {
  batch_no: string
  chain: TraceNode[]
  weight_chain: Record<string, any>[]
  chain_length: number
  complete: boolean
  frozen_count: number
}

export interface GateDetail {
  batch_no: string
  passed: boolean
  message: string
  testing_checks: { total: number; confirmed: number }
  certification_checks: { total: number; confirmed: number }
}

export interface WeightConservation {
  batch_no: string
  picking_weight: number
  final_weight: number
  total_loss_pct: number
  conservation_ok: boolean
}

export async function fetchTraceChain(batchNo: string): Promise<TraceChain> {
  return fetchJson<TraceChain>(`${API}/${batchNo}/trace`)
}

export async function advanceBatch(
  batchNo: string,
  currentModule: string,
  currentEntryId: number,
  requestId?: string
): Promise<{ ok: boolean; message: string; entry: Record<string, any> }> {
  const params = new URLSearchParams({
    current_module: currentModule,
    current_entry_id: String(currentEntryId),
  })
  if (requestId) params.set('request_id', requestId)
  return fetchJson(`${API}/${batchNo}/advance?${params.toString()}`)
}

export async function checkGate(batchNo: string): Promise<{ ok: boolean; detail: GateDetail }> {
  return fetchJson(`${API}/${batchNo}/gate`)
}

export async function checkWeightConservation(batchNo: string): Promise<{
  ok: boolean; detail: WeightConservation
}> {
  return fetchJson(`${API}/${batchNo}/weight-conservation`)
}

export async function recalcMoisture(
  batchNo: string,
  processModule: string
): Promise<{ ok: boolean; detail: Record<string, any> }> {
  return fetchJson(`${API}/${batchNo}/moisture-recalc?process_module=${processModule}`)
}

export async function freezeDownstream(
  batchNo: string,
  defectEntryId: number,
  reason: string
): Promise<{ ok: boolean; frozen_count: number; frozen_keys: string[] }> {
  const params = new URLSearchParams({
    defect_entry_id: String(defectEntryId),
    reason,
  })
  return fetchJson(`${API}/${batchNo}/freeze-downstream?${params.toString()}`)
}

export async function linkSample(
  sampleEntryId: number,
  processModule: string,
  processEntryId: number
): Promise<{ ok: boolean; message: string }> {
  const params = new URLSearchParams({
    process_module: processModule,
    process_entry_id: String(processEntryId),
  })
  const response = await request(
    `${API}/sample/${sampleEntryId}/link?${params.toString()}`,
    { method: 'POST' }
  )
  if (!response.ok) {
    throw new Error('SAMPLE_LINK_FAILED')
  }
  return response.json()
}

export async function updateAuditReview(
  auditEntryId: number,
  reviewConclusion: string
): Promise<{ ok: boolean; message: string }> {
  const response = await request(
    `${API}/audit/${auditEntryId}/review?review_conclusion=${encodeURIComponent(reviewConclusion)}`,
    { method: 'POST' }
  )
  if (!response.ok) {
    throw new Error('AUDIT_REVIEW_FAILED')
  }
  return response.json()
}