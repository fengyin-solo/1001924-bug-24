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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="acting"
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
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: string | number }

const ENDPOINT = '/api/substation'
const columns = ["站区编号", "主变容量", "电压等级", "所属场站", "上次检修日", "值班班组", "负荷率", "升压站状态"]
const actions = ["确认检修", "登记负荷越限", "停运升压站"]
const statuses = ["待检修", "运行正常", "负荷越限", "已停运"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([
  { label: '在运升压站', value: 0 },
  { label: '负荷越限站数', value: 0 },
  { label: '平均负荷率', value: '—' },
])
const errorMessage = ref('')
const acting = ref(false)
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '升压站登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (acting.value) {
    return
  }
  acting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || `升压站动作未生效（接口返回 ${response.status}）`)
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '升压站操作失败'
  } finally {
    acting.value = false
  }
}

async function loadSummary() {
  try {
    const payload = await fetchJson<{ stats: StatCard[] }>(`${ENDPOINT}/summary`)
    stats.value = payload.stats ?? []
  } catch {
    // 统计卡刷新失败时保留旧值，错误提示交给列表的请求通道
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('升压站列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '升压站列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
