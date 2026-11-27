<template>
  <div class="pipeline-dashboard">
    <header class="view-header">
      <h2>工序推进看板</h2>
      <p>管理批次血缘链，推进制茶工序，查看门禁状态</p>
    </header>

    <div class="dashboard-grid">
      <!-- 左侧：批次操作面板 -->
      <div class="panel batch-operations">
        <h3>批次操作</h3>
        <div class="form-group">
          <label>批次号</label>
          <input v-model="batchNo" placeholder="输入批次号，如 BATCH-000001" />
        </div>
        <div class="form-group">
          <label>当前工序</label>
          <select v-model="currentModule">
            <option value="picking">鲜叶采摘</option>
            <option value="withering">萎凋</option>
            <option value="fixing">杀青</option>
            <option value="rolling">揉捻</option>
            <option value="fermentation">发酵</option>
            <option value="drying">干燥</option>
            <option value="grading">精制分级</option>
            <option value="blending">拼配</option>
            <option value="packing">包装</option>
            <option value="trace_code">溯源码段</option>
          </select>
        </div>
        <div class="form-group">
          <label>当前记录ID</label>
          <input v-model.number="currentEntryId" type="number" placeholder="输入记录ID" />
        </div>
        <div class="button-group">
          <button class="btn primary" @click="doAdvance" :disabled="advancing">
            {{ advancing ? '推进中…' : '推进工序' }}
          </button>
          <button class="btn" @click="doCheckGate">门禁检查</button>
          <button class="btn" @click="doTrace">查看追溯链</button>
        </div>
        <div v-if="advanceMsg" class="result-msg" :class="advanceOk ? 'success' : 'error'">
          {{ advanceMsg }}
        </div>
      </div>

      <!-- 右侧：门禁状态 -->
      <div class="panel gate-status">
        <h3>门禁状态</h3>
        <div v-if="gateDetail" class="gate-cards">
          <div class="gate-card">
            <div class="gate-label">检测报告</div>
            <div class="gate-value">
              已签收 {{ gateDetail.testing_checks.confirmed }} / {{ gateDetail.testing_checks.total }}
            </div>
            <div class="gate-icon" :class="gateDetail.testing_checks.confirmed > 0 ? 'pass' : 'fail'">
              {{ gateDetail.testing_checks.confirmed > 0 ? '✓' : '✗' }}
            </div>
          </div>
          <div class="gate-card">
            <div class="gate-label">认证资质</div>
            <div class="gate-value">
              已确认 {{ gateDetail.certification_checks.confirmed }} / {{ gateDetail.certification_checks.total }}
            </div>
            <div class="gate-icon" :class="gateDetail.certification_checks.confirmed > 0 ? 'pass' : 'fail'">
              {{ gateDetail.certification_checks.confirmed > 0 ? '✓' : '✗' }}
            </div>
          </div>
          <div class="gate-summary">
            门禁结论：<strong :class="gateDetail.passed ? 'pass' : 'fail'">
              {{ gateDetail.passed ? '通过' : '不通过' }}
            </strong>
            <div v-if="gateDetail.message" class="gate-reason">{{ gateDetail.message }}</div>
          </div>
        </div>
        <div v-else class="gate-empty">
          请先执行门禁检查
        </div>
      </div>

      <!-- 下方：重量守恒 -->
      <div class="panel weight-panel" v-if="weightData">
        <h3>重量守恒</h3>
        <div class="weight-stats">
          <div class="stat">
            <span class="stat-label">鲜叶重量</span>
            <span class="stat-value">{{ weightData.picking_weight }} kg</span>
          </div>
          <div class="stat">
            <span class="stat-label">最终产出</span>
            <span class="stat-value">{{ weightData.final_weight }} kg</span>
          </div>
          <div class="stat">
            <span class="stat-label">总损耗率</span>
            <span class="stat-value">{{ weightData.total_loss_pct }}%</span>
          </div>
          <div class="stat">
            <span class="stat-label">守恒状态</span>
            <span class="stat-value" :class="weightData.conservation_ok ? 'pass' : 'fail'">
              {{ weightData.conservation_ok ? '正常' : '异常' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 下方：锅温日志与接料 -->
      <div class="panel pan-panel">
        <h3>锅温日志与揉捻接料</h3>
        <div class="pan-summary">
          <span class="pan-mode" :class="panState?.mode">
            当前口径：{{ panState?.mode === 'legacy' ? '旧版锅温设定（回滚中）' : '新版锅温日志' }}
          </span>
          <span>锅温日志 {{ panState?.logs ?? 0 }} 条（含迁移旧来源 {{ panState?.legacy_logs ?? 0 }} 条）</span>
          <span>有效接料证明 {{ panState?.proofs ?? 0 }} 份</span>
          <span>已接料 {{ panState?.receipts ?? 0 }} 锅</span>
          <button class="btn" type="button" @click="doLoadPan">刷新</button>
        </div>
        <div v-if="pendingReceiving.length" class="pending-list">
          <h4>待接料锅（未办成的旧记录仍可继续查）</h4>
          <div v-for="item in pendingReceiving" :key="item.锅号" class="pending-row">
            <strong>{{ item.锅号 }}</strong>
            <span>杀青记录 #{{ item.杀青记录ID }}</span>
            <span>出料 {{ item.出料重量 || '—' }}kg</span>
            <span class="pending-note">{{ item.核对?.说明 || '—' }}</span>
          </div>
        </div>
        <div v-else class="gate-empty">暂无待接料锅</div>
        <div class="pan-actions">
          <label class="pan-pot">
            锅号
            <input v-model="proofPot" placeholder="如 FIXING#3 或 POT-A" />
          </label>
          <button class="btn" type="button" @click="doLoadProof">查锅温证明</button>
          <button class="btn" type="button" @click="doQueryLegacy">旧口径回查</button>
          <button class="btn ghost" type="button" @click="doSwitchMode(panState?.mode === 'legacy' ? 'new' : 'legacy')">
            {{ panState?.mode === 'legacy' ? '切回新版' : '回滚旧版' }}
          </button>
        </div>
        <div v-if="proofView" class="proof-view">
          <div class="proof-title">锅号 {{ proofView.锅号 }} 核对结论</div>
          <p class="proof-desc">{{ proofView.核对?.说明 || '—' }}</p>
          <p class="proof-desc">
            原旧凭据继续受理：{{ proofView.核对?.原旧凭据继续受理 ? '是' : '否' }} ｜
            需确认刚来的锅温日志：{{ proofView.核对?.需要确认刚来的锅温日志 ? '是' : '否' }} ｜
            实际采用：{{ proofView.核对?.实际采用 || '—' }}
          </p>
          <div v-for="(source, idx) in proofView.告知来源" :key="idx" class="source-row">
            <span>{{ source.来源 }}</span>
            <span>{{ source.日志编号 }}</span>
            <span>{{ source.来源 === '旧锅温设定' ? source.锅温设定 : source.实测锅温 + '℃' }}</span>
            <span>{{ source.测温时间 || '无测量时间' }}</span>
            <span>{{ source.口径 }}</span>
          </div>
        </div>
        <div v-if="legacyView" class="proof-view">
          <div class="proof-title">旧口径回查（已确认锅温设定 / 出料重量）</div>
          <div v-for="item in legacyView" :key="item.id" class="source-row">
            <span>#{{ item.id }} {{ item.锅号 }}</span>
            <span>设定 {{ item.锅温设定 }}</span>
            <span>出料 {{ item.出料重量 || '—' }}</span>
            <span>{{ item.口径 }} · 非实测</span>
          </div>
        </div>
        <div v-if="panMessage" class="result-msg success">{{ panMessage }}</div>
      </div>

      <!-- 追溯链展示 -->
      <div class="panel trace-panel" v-if="traceData">
        <h3>批次 {{ traceData.batch_no }} 追溯链 ({{ traceData.chain_length }} 步)</h3>
        <div class="trace-chain">
          <div v-for="(node, idx) in traceData.chain" :key="idx" class="trace-node">
            <div class="node-header">
              <span class="node-index">{{ idx + 1 }}</span>
              <span class="node-module">{{ getModuleName(node.module) }}</span>
              <span class="node-status" :class="node.data?.status">
                {{ node.data?.status || '-' }}
              </span>
            </div>
            <div class="node-detail" v-if="node.data">
              ID: {{ node.entry_id }} | 
              编号: {{ node.data['登记编号'] }} | 
              <span v-if="node.data['鲜叶重量']">重量: {{ node.data['鲜叶重量'] }}kg</span>
              <span v-if="node.data['产出重量']">产出: {{ node.data['产出重量'] }}kg</span>
              <span v-if="node.data['损耗率']">损耗: {{ node.data['损耗率'] }}%</span>
            </div>
          </div>
          <div v-if="traceData.frozen_count > 0" class="frozen-banner">
            该批次有 {{ traceData.frozen_count }} 条记录被冻结
          </div>
        </div>
      </div>
    </div>

    <!-- 工序流程图 -->
    <div class="process-flow">
      <h3>制茶工序流程</h3>
      <div class="flow-steps">
        <div v-for="(step, idx) in flowSteps" :key="idx" class="flow-step"
          :class="{ active: step.key === currentModule }">
          <div class="step-num">{{ idx + 1 }}</div>
          <div class="step-name">{{ step.name }}</div>
          <div class="step-arrow" v-if="idx < flowSteps.length - 1">→</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  advanceBatch,
  checkGate,
  checkWeightConservation,
  fetchTraceChain,
  fetchPanProof,
  fetchPanState,
  fetchPendingReceiving,
  fetchLegacyQuery,
} from '@/api/pipeline-client'
import { request } from '@/api/client'

const batchNo = ref('')
const currentModule = ref('picking')
const currentEntryId = ref(0)
const advancing = ref(false)
const advanceMsg = ref('')
const advanceOk = ref(false)
const gateDetail = ref<any>(null)
const weightData = ref<any>(null)
const traceData = ref<any>(null)

const flowSteps = [
  { key: 'picking', name: '鲜叶采摘' },
  { key: 'withering', name: '萎凋' },
  { key: 'fixing', name: '杀青' },
  { key: 'rolling', name: '揉捻' },
  { key: 'fermentation', name: '发酵' },
  { key: 'drying', name: '干燥' },
  { key: 'grading', name: '精制分级' },
  { key: 'blending', name: '拼配' },
  { key: 'packing', name: '包装' },
  { key: 'trace_code', name: '溯源码' },
  { key: 'shipment', name: '发运' },
]

const moduleNames: Record<string, string> = {
  picking: '鲜叶采摘', withering: '萎凋', fixing: '杀青',
  rolling: '揉捻', fermentation: '发酵', drying: '干燥',
  grading: '精制分级', blending: '拼配', packing: '包装',
  trace_code: '溯源码段', shipment: '发运交接',
  tea_garden: '茶园地块', testing: '检测报告', certification: '认证资质',
  storage: '仓储养护', sample: '样品留样', defect: '不合格处置', audit: '内审巡查',
}

function getModuleName(key: string): string {
  return moduleNames[key] || key
}

async function doAdvance() {
  advancing.value = true
  advanceMsg.value = ''
  try {
    const reqId = `advance-${Date.now()}`
    const result = await advanceBatch(batchNo.value, currentModule.value, currentEntryId.value, reqId)
    advanceOk.value = result.ok
    advanceMsg.value = result.message
    if (result.ok && result.entry) {
      advanceMsg.value += ` (新记录ID: ${result.entry.id})`
    }
  } catch (err: any) {
    advanceOk.value = false
    advanceMsg.value = err.message || '推进失败'
  } finally {
    advancing.value = false
  }
}

async function doCheckGate() {
  try {
    const result = await checkGate(batchNo.value)
    gateDetail.value = result.detail
  } catch (err: any) {
    gateDetail.value = { passed: false, message: err.message }
  }
}

async function doTrace() {
  try {
    const result = await fetchTraceChain(batchNo.value)
    traceData.value = result
    // 同时获取重量守恒
    try {
      const wc = await checkWeightConservation(batchNo.value)
      weightData.value = wc.detail
    } catch {
      weightData.value = null
    }
  } catch (err: any) {
    traceData.value = null
    advanceMsg.value = err.message || '追溯链查询失败'
  }
}

// ── 锅温日志与接料 ──
const panState = ref<any>(null)
const pendingReceiving = ref<any[]>([])
const proofPot = ref('')
const proofView = ref<any>(null)
const legacyView = ref<any[] | null>(null)
const panMessage = ref('')

async function doLoadPan() {
  panMessage.value = ''
  try {
    panState.value = await fetchPanState()
    pendingReceiving.value = (await fetchPendingReceiving()).items
  } catch (err: any) {
    panMessage.value = err.message || '锅温状态读取失败'
  }
}

async function doLoadProof() {
  panMessage.value = ''
  if (!proofPot.value.trim()) {
    panMessage.value = '请先输入锅号'
    return
  }
  try {
    proofView.value = await fetchPanProof(proofPot.value.trim())
    legacyView.value = null
  } catch (err: any) {
    panMessage.value = err.message || '锅温证明查询失败'
  }
  await doLoadPan()
}

async function doQueryLegacy() {
  panMessage.value = ''
  try {
    legacyView.value = (await fetchLegacyQuery()).items
    proofView.value = null
  } catch (err: any) {
    panMessage.value = err.message || '旧口径回查失败'
  }
}

async function doSwitchMode(mode: string) {
  panMessage.value = ''
  try {
    const response = await request('/api/pan/mode', {
      method: 'POST',
      body: JSON.stringify({ mode }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.detail || '口径切换失败')
    panMessage.value = payload.message
  } catch (err: any) {
    panMessage.value = err.message || '口径切换失败'
  }
  await doLoadPan()
}

onMounted(doLoadPan)
</script>

<style scoped>
.pipeline-dashboard {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.view-header {
  margin-bottom: 24px;
}

.view-header h2 {
  font-size: 24px;
  color: #2c3e50;
  margin-bottom: 8px;
}

.view-header p {
  color: #7f8c8d;
  font-size: 14px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.panel {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.panel h3 {
  font-size: 16px;
  color: #2c3e50;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid #eee;
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-size: 13px;
  color: #7f8c8d;
  margin-bottom: 4px;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  box-sizing: border-box;
}

.button-group {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.btn {
  padding: 8px 16px;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: white;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:hover {
  background: #f5f5f5;
}

.btn.primary {
  background: #3498db;
  color: white;
  border-color: #3498db;
}

.btn.primary:hover {
  background: #2980b9;
}

.btn.primary:disabled {
  background: #bdc3c7;
  border-color: #bdc3c7;
  cursor: not-allowed;
}

.result-msg {
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
}

.result-msg.success {
  background: #d4edda;
  color: #155724;
  border: 1px solid #c3e6cb;
}

.result-msg.error {
  background: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}

.gate-cards {
  display: grid;
  gap: 12px;
}

.gate-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 6px;
}

.gate-label {
  font-size: 14px;
  color: #2c3e50;
  font-weight: 500;
}

.gate-value {
  font-size: 13px;
  color: #7f8c8d;
}

.gate-icon {
  font-size: 18px;
  font-weight: bold;
}

.gate-icon.pass {
  color: #27ae60;
}

.gate-icon.fail {
  color: #e74c3c;
}

.gate-summary {
  margin-top: 12px;
  padding: 12px;
  border-radius: 6px;
  font-size: 14px;
}

.gate-summary .pass {
  color: #27ae60;
}

.gate-summary .fail {
  color: #e74c3c;
}

.gate-reason {
  margin-top: 4px;
  font-size: 12px;
  color: #7f8c8d;
}

.gate-empty {
  text-align: center;
  color: #bdc3c7;
  padding: 24px;
}

.weight-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat {
  text-align: center;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 6px;
}

.stat-label {
  display: block;
  font-size: 12px;
  color: #7f8c8d;
  margin-bottom: 4px;
}

.stat-value {
  display: block;
  font-size: 18px;
  font-weight: bold;
  color: #2c3e50;
}

.stat-value.pass { color: #27ae60; }
.stat-value.fail { color: #e74c3c; }

.trace-panel {
  grid-column: 1 / -1;
}

.trace-chain {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trace-node {
  flex: 0 0 calc(33.33% - 8px);
  min-width: 200px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 6px;
  border-left: 3px solid #3498db;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.node-index {
  width: 24px;
  height: 24px;
  background: #3498db;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
}

.node-module {
  font-size: 14px;
  font-weight: 500;
  color: #2c3e50;
}

.node-status {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 3px;
  margin-left: auto;
}

.node-status.已确认 { background: #d4edda; color: #155724; }
.node-status.草稿 { background: #fff3cd; color: #856404; }
.node-status.待确认 { background: #cce5ff; color: #004085; }
.node-status.已撤回 { background: #f8d7da; color: #721c24; }

.node-detail {
  font-size: 12px;
  color: #7f8c8d;
}

.frozen-banner {
  width: 100%;
  padding: 8px 12px;
  background: #fce4ec;
  color: #c62828;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
  margin-top: 8px;
}

.pan-panel {
  grid-column: 1 / -1;
}
.pan-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  font-size: 13px;
  color: #555;
  margin-bottom: 12px;
}
.pan-mode {
  padding: 3px 10px;
  border-radius: 4px;
  font-weight: 500;
  background: #d4edda;
  color: #155724;
}
.pan-mode.legacy {
  background: #fff3cd;
  color: #856404;
}
.pending-list h4 { font-size: 13px; margin: 8px 0; color: #2c3e50; }
.pending-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 6px 8px;
  background: #f8f9fa;
  border-radius: 4px;
  font-size: 12px;
  margin-bottom: 4px;
}
.pending-note { color: #856404; }
.pan-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 12px 0;
}
.pan-pot { font-size: 12px; color: #666; display: flex; align-items: center; gap: 6px; }
.pan-pot input {
  padding: 6px 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 13px;
}
.proof-view { margin-top: 8px; padding: 10px; background: #f3f8ff; border-radius: 4px; }
.proof-title { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.proof-desc { font-size: 12px; color: #555; margin: 2px 0; }
.source-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  padding: 4px 6px;
  border-bottom: 1px dashed #e0e0e0;
}

.process-flow {
  margin-top: 24px;
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.process-flow h3 {
  font-size: 16px;
  color: #2c3e50;
  margin-bottom: 16px;
}

.flow-steps {
  display: flex;
  align-items: center;
  overflow-x: auto;
  gap: 0;
  padding: 8px 0;
}

.flow-step {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px;
  background: #f8f9fa;
  margin-right: 4px;
  font-size: 12px;
  white-space: nowrap;
}

.flow-step.active {
  background: #3498db;
  color: white;
}

.step-num {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #bdc3c7;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  margin-right: 6px;
}

.flow-step.active .step-num {
  background: white;
  color: #3498db;
}

.step-name {
  font-weight: 500;
}

.step-arrow {
  margin: 0 4px;
  color: #bdc3c7;
  font-size: 14px;
}
</style>