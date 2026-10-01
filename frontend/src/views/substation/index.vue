<template>
  <section class="page" data-module="substation">
    <header class="page-head">
      <div>
        <h2>升压站管理</h2>
        <p class="page-desc">维护升压站，围绕站区编号、主变容量、电压等级、所属场站做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记升压站</button>
        <button class="btn" type="button" @click="exportRows">导出升压站清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>升压站状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="statusName in statuses" :key="statusName" :value="statusName">
            {{ statusName }}
          </option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <!-- 状态列与详情共用后端 status 口径，不再读台账占位文本 -->
          <td v-for="column in columns" :key="column">
            {{ column === '升压站状态' ? (row.status ?? '—') : (row[column] ?? '—') }}
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="busyActionId === row.id"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无升压站数据，可先登记升压站</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条升压站记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="createOpen" class="modal-mask" @click.self="closeCreate">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记升压站</h3>
        <label v-for="field in createFields" :key="field" class="filter-item">
          <span>{{ field }}{{ requiredFields.includes(field) ? '（必填）' : '' }}</span>
          <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="row-actions">
          <button class="btn primary" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '提交登记' }}
          </button>
          <button class="btn ghost" type="button" :disabled="submitting" @click="closeCreate">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Summary = { inService: number; overloaded: number; avgLoadRate: number }

const ENDPOINT = '/api/substation'
const columns = ["站区编号", "主变容量", "电压等级", "所属场站", "上次检修日", "值班班组", "负荷率", "升压站状态"]
const actions = ["确认检修", "登记负荷越限", "停运升压站"]
const statuses = ["待检修", "运行正常", "负荷越限", "已停运"]
// 站区编号沿用既有台账字段，不另起一套编号
const createFields = ["站区编号", "主变容量", "电压等级", "所属场站", "上次检修日", "值班班组", "负荷率"]
const requiredFields = ["站区编号", "主变容量", "电压等级"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '在运升压站', value: 0 },
  { label: '负荷越限站数', value: 0 },
  { label: '平均负荷率', value: '0%' },
])

const createOpen = ref(false)
const submitting = ref(false)
const createError = ref('')
const createForm = reactive<Record<string, string>>({})
// 行内动作锁：同一张站区编号的在途请求只允许一个，避免并发重复提交
const busyActionId = ref<Row['id'] | null>(null)

function applySummary(summary?: Summary | null) {
  // 页头卡片与列表、看板同一份口径，全部由后端 summary 给出
  stats.value = [
    { label: '在运升压站', value: summary?.inService ?? 0 },
    { label: '负荷越限站数', value: summary?.overloaded ?? 0 },
    { label: '平均负荷率', value: `${summary?.avgLoadRate ?? 0}%` },
  ]
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  for (const field of createFields) {
    createForm[field] = ''
  }
  createError.value = ''
  createOpen.value = true
}

function closeCreate() {
  if (submitting.value) {
    return
  }
  createOpen.value = false
}

async function submitCreate() {
  createError.value = ''
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '升压站登记未生效，请稍后重试')
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '升压站登记失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  if (busyActionId.value !== null) {
    return
  }
  errorMessage.value = ''
  busyActionId.value = row.id
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    // 业务失败（HTTP 200 但 ok=false，如已停运/重复编号）也要把原因露出来
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '升压站动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '升压站操作失败'
  } finally {
    busyActionId.value = null
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value)),
  ).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('升压站列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    applySummary(payload.summary)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '升压站列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 420px;
  background: #fff;
  border-radius: 8px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.modal h3 { margin: 0 0 4px; }
.link:disabled { color: #94a3b8; cursor: not-allowed; }
</style>
