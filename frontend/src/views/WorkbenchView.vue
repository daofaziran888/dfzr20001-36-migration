<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 批次追溯链面板 -->
    <div v-if="showTrace && traceBatchNo" class="trace-panel">
      <h4>批次 {{ traceBatchNo }} 追溯链</h4>
      <div v-if="traceLoading">加载中...</div>
      <div v-else-if="traceError" class="error-text">{{ traceError }}</div>
      <div v-else class="trace-chain-inline">
        <div v-for="(node, idx) in traceChain" :key="idx" class="trace-node-inline"
          :class="{ frozen: node.frozen }">
          <div class="node-index">{{ idx + 1 }}</div>
          <div class="node-info">
            <strong>{{ getProcessName(node.module) }}</strong>
            <span>ID:{{ node.entry_id }}</span>
            <span class="node-status-tag" :class="node.status">{{ node.status }}</span>
          </div>
          <div v-if="node.data" class="node-meta">
            <span v-if="node.data['鲜叶重量'] || node.data['投入重量']">
              重量: {{ node.data['鲜叶重量'] || node.data['投入重量'] }}kg
            </span>
            <span v-if="node.data['产出重量']">→ 产出: {{ node.data['产出重量'] }}kg</span>
          </div>
          <div v-if="idx < traceChain.length - 1" class="trace-arrow">→</div>
        </div>
      </div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button
              v-if="row['批次号']"
              class="link trace-link"
              type="button"
              @click="viewBatchTrace(String(row['批次号']))"
              title="查看批次追溯">
              批次追溯
            </button>
            <button
              v-if="isProcessModule && row['上游记录ID']"
              class="link upstream-link"
              type="button"
              @click="viewUpstream(row)" title="查看上游工序">
              查看上游
            </button>
            <button
              v-if="meta.key === 'rolling'"
              class="link proof-link"
              data-testid="receiving-proof"
              type="button"
              @click="openRollingProof(row)" title="查锅温接料证明">
              接料证明
            </button>
            <button
              v-if="meta.key === 'fixing'"
              class="link proof-link"
              data-testid="fixing-proof"
              type="button"
              @click="openFixingProof(row)" title="查看锅温告知来源">
              锅温证明
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 锅温 / 接料证明面板：旧口径与新日志两种告知来源都在这里核对 -->
    <div v-if="proofPanel" class="proof-panel" data-testid="proof-panel">
      <div class="proof-head">
        <h4>{{ proofPanel.title }} · 锅号 {{ proofPanel.pot }}</h4>
        <button class="btn ghost" type="button" @click="proofPanel = null">关闭</button>
      </div>
      <div v-if="proofPanel.loading">加载中...</div>
      <div v-else-if="proofPanel.error" class="error-text">{{ proofPanel.error }}</div>
      <div v-else class="proof-body">
        <p class="proof-note">{{ proofPanel.plan.核对?.说明 || '—' }}</p>
        <div class="proof-tags">
          <span class="proof-tag" :class="proofPanel.plan.核对?.原旧凭据继续受理 ? 'ok' : 'muted'">
            原旧凭据继续受理：{{ proofPanel.plan.核对?.原旧凭据继续受理 ? '是' : '否' }}
          </span>
          <span class="proof-tag" :class="proofPanel.plan.核对?.需要确认刚来的锅温日志 ? 'warn' : 'muted'">
            需确认刚来的锅温日志：{{ proofPanel.plan.核对?.需要确认刚来的锅温日志 ? '是' : '否' }}
          </span>
          <span class="proof-tag" :class="proofPanel.plan.核对?.实际采用 ? 'ok' : 'muted'">
            实际采用：{{ proofPanel.plan.核对?.实际采用 || '—' }}
          </span>
        </div>
        <table class="mini-table">
          <thead>
            <tr>
              <th>来源</th><th>日志编号</th><th>温度</th><th>测量时间</th><th>口径</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(source, idx) in proofPanel.plan.告知来源" :key="idx">
              <td>{{ source.来源 }}</td>
              <td>{{ source.日志编号 }}</td>
              <td>{{ source.来源 === '旧锅温设定' ? (source.锅温设定 ?? '—') : (source.实测锅温 ?? '—') }}</td>
              <td>{{ source.测温时间 || '—' }}</td>
              <td>{{ source.口径 }}</td>
              <td>
                <span v-if="source.来源 === '旧锅温设定'">{{ source.可受理 ? '可受理' : '待确认/不可受理' }}</span>
                <span v-else>{{ source.状态 }}{{ source.有测量时间 ? '' : '（缺测量时间）' }}</span>
              </td>
            </tr>
            <tr v-if="!proofPanel.plan.告知来源?.length">
              <td colspan="6" class="empty-state">该锅还没有任何锅温告知来源</td>
            </tr>
          </tbody>
        </table>
        <div class="proof-proof">
          <span v-if="proofPanel.plan.有效证明">
            有效接料证明：{{ proofPanel.plan.有效证明['证明编号'] }}
            （{{ proofPanel.plan.有效证明['凭据版本'] }}
            <template v-if="proofPanel.plan.有效证明['实测']">，实测 {{ proofPanel.plan.有效证明['温度'] }}℃</template>
            ）
          </span>
          <span v-else>尚未形成有效接料证明</span>
        </div>
        <div v-if="proofPanel.rollingId" class="page-actions">
          <button
            class="btn primary"
            data-testid="receive-confirm"
            type="button"
            :disabled="proofPanel.receiving || !!proofPanel.plan.已接料"
            @click="confirmReceive"
          >
            {{ proofPanel.plan.已接料 ? '已接料' : '完成接料' }}
          </button>
          <span class="proof-note">
            已办成接料：{{ proofPanel.plan.已接料 ? proofPanel.plan.已接料['凭据编号'] + '（' + proofPanel.plan.已接料['凭据版本'] + '）' : '—' }}
          </span>
        </div>
      </div>
    </div>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}<em v-if="meta.optionalFields?.includes(field)">（可空）</em></span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" :required="!meta.optionalFields?.includes(field)" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createEntry,
  downloadEntries,
  listEntries,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import { emptyPlan, fetchTraceChain, fetchPanProof, fetchReceivingPlan, receiveRolling } from '@/api/pipeline-client'
import type { ReceivingPlan } from '@/api/pipeline-client'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const router = useRouter()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

// 工序模块判断
const PROCESS_ORDER = ['picking', 'withering', 'fixing', 'rolling', 'fermentation', 'drying',
  'grading', 'blending', 'packing', 'trace_code', 'shipment']
const PROCESS_NAMES: Record<string, string> = {
  picking: '鲜叶采摘', withering: '萎凋', fixing: '杀青',
  rolling: '揉捻', fermentation: '发酵', drying: '干燥',
  grading: '精制分级', blending: '拼配', packing: '包装',
  trace_code: '溯源码段', shipment: '发运交接',
}
const isProcessModule = computed(() => PROCESS_ORDER.includes(meta.key))
// 批次追溯
const showTrace = ref(false)
const traceBatchNo = ref('')
const traceChain = ref<any[]>([])
const traceLoading = ref(false)
const traceError = ref('')

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function getProcessName(module: string): string {
  return PROCESS_NAMES[module] || module
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  // 新口径杀青只填锅温日志，旧口径才填锅温设定；两种来源都不强制二选一必填。
  if (meta.key === 'fixing') createValues.value['锅温设定'] = ''
  if (meta.key === 'rolling') createValues.value['锅号'] = ''
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    if (meta.key === 'rolling' && proofPanel.value) {
      await loadRollingProof(Number(row.id))
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

// ── 锅温日志 / 接料证明 ──
const proofPanel = ref<null | {
  title: string
  pot: string
  rollingId?: number
  loading: boolean
  receiving: boolean
  error: string
  plan: ReceivingPlan
}>(null)

function potOfFixing(row: EntryRow): string {
  return String(row['锅号'] || `FIXING#${row.id}`)
}

async function openFixingProof(row: EntryRow) {
  const pot = potOfFixing(row)
  proofPanel.value = {
    title: '杀青锅温告知来源', pot, loading: true, receiving: false, error: '',
    plan: emptyPlan(pot),
  }
  try {
    proofPanel.value.plan = await fetchPanProof(pot)
  } catch (error) {
    proofPanel.value.error = error instanceof Error ? error.message : '锅温证明查询失败'
  } finally {
    if (proofPanel.value) proofPanel.value.loading = false
  }
}

async function loadRollingProof(rollingId: number) {
  try {
    const plan = await fetchReceivingPlan(rollingId)
    if (proofPanel.value) {
      proofPanel.value.plan = plan
      proofPanel.value.pot = plan.锅号
    }
  } catch (error) {
    if (proofPanel.value) {
      proofPanel.value.error = error instanceof Error ? error.message : '接料证明查询失败'
    }
  }
}

async function openRollingProof(row: EntryRow) {
  const rollingId = Number(row.id)
  const pot = String(row['锅号'] || '')
  proofPanel.value = {
    title: '揉捻接料证明', pot, rollingId, loading: true, receiving: false, error: '',
    plan: { ...emptyPlan(pot), 揉捻记录ID: rollingId, 已接料: null },
  }
  await loadRollingProof(rollingId)
  if (proofPanel.value) proofPanel.value.loading = false
}

async function confirmReceive() {
  if (!proofPanel.value?.rollingId) return
  proofPanel.value.receiving = true
  errorMessage.value = ''
  try {
    const result = await receiveRolling(proofPanel.value.rollingId)
    await loadRollingProof(proofPanel.value.rollingId)
    await reload()
    if (!result.ok) throw new Error(result.message)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '接料失败'
    if (proofPanel.value) await loadRollingProof(proofPanel.value.rollingId)
  } finally {
    if (proofPanel.value) proofPanel.value.receiving = false
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

async function viewBatchTrace(batchNo: string) {  traceBatchNo.value = batchNo
  showTrace.value = true
  traceLoading.value = true
  traceError.value = ''
  try {
    const result = await fetchTraceChain(batchNo)
    traceChain.value = (result.chain || []).map((node: any) => ({
      ...node,
      frozen: false,
      status: node.data?.status || '',
    }))
  } catch (err: any) {
    traceError.value = err.message || '追溯链查询失败'
    traceChain.value = []
  } finally {
    traceLoading.value = false
  }
}

function viewUpstream(row: EntryRow) {
  const upstreamModule = row['上游工序']
  const upstreamId = row['上游记录ID']
  if (upstreamModule && upstreamId) {
    void router.push({ name: 'module', params: { moduleKey: String(upstreamModule) } })
  }
}

onMounted(reload)
</script>

<style scoped>
.trace-panel {
  margin-bottom: 12px;
  padding: 12px 16px;
  background: #f3f8ff;
  border-radius: 6px;
  border-left: 3px solid #3498db;
}
.trace-panel h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #2c3e50;
}
.trace-chain-inline {
  display: flex;
  align-items: flex-start;
  overflow-x: auto;
  gap: 4px;
  padding: 8px 0;
}
.trace-node-inline {
  flex: 0 0 auto;
  min-width: 130px;
  padding: 8px;
  background: white;
  border-radius: 4px;
  border: 1px solid #ddd;
  font-size: 11px;
}
.trace-node-inline.frozen {
  border-color: #e74c3c;
  background: #fce4ec;
}
.node-index {
  width: 18px;
  height: 18px;
  background: #3498db;
  color: white;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  margin-right: 4px;
}
.node-info strong {
  display: block;
  font-size: 11px;
}
.node-info span {
  display: block;
  color: #7f8c8d;
  font-size: 10px;
}
.node-status-tag {
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 9px;
  display: inline-block;
}
.node-status-tag.已确认 { background: #d4edda; color: #155724; }
.node-status-tag.草稿 { background: #fff3cd; color: #856404; }
.node-status-tag.待确认 { background: #cce5ff; color: #004085; }
.node-status-tag.已撤回 { background: #f8d7da; color: #721c24; }
.node-meta {
  margin-top: 2px;
  font-size: 9px;
  color: #7f8c8d;
}
.trace-arrow {
  color: #3498db;
  font-size: 14px;
  margin: 0 2px;
  padding-top: 8px;
}
.trace-link, .upstream-link, .proof-link {
  color: #27ae60 !important;
  margin-left: 6px;
  padding: 2px 6px;
  font-size: 11px;
  border: 1px solid #27ae60;
  border-radius: 3px;
  text-decoration: none;
  cursor: pointer;
}
.trace-link:hover, .upstream-link:hover, .proof-link:hover {
  background: #27ae60;
  color: white !important;
}
.proof-panel {
  margin-bottom: 12px;
  padding: 14px 16px;
  background: #fffaf0;
  border-radius: 6px;
  border-left: 3px solid #e67e22;
}
.proof-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.proof-head h4 { margin: 0; font-size: 14px; color: #2c3e50; }
.proof-body { font-size: 12px; color: #444; }
.proof-note { margin: 6px 0; color: #856404; }
.proof-tags { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; }
.proof-tag {
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 11px;
  background: #eee;
}
.proof-tag.ok { background: #d4edda; color: #155724; }
.proof-tag.warn { background: #fff3cd; color: #856404; }
.proof-tag.muted { background: #eceff1; color: #607d8b; }
.mini-table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 11px; }
.mini-table th, .mini-table td { border: 1px solid #e0e0e0; padding: 4px 6px; text-align: left; }
.mini-table th { background: #f5f5f5; }
.proof-proof { margin: 8px 0; font-weight: 500; color: #2c3e50; }
.proof-body .page-actions { display: flex; align-items: center; gap: 10px; }
</style>