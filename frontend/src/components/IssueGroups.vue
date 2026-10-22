<script setup>
import { computed } from 'vue'

const props = defineProps({ items: { type: Array, default: () => [] }, rules: { type: Object, default: () => ({}) } })

const SEV = { error: '错误', warning: '警告', info: '提示' }
const FIX = { auto: '可自动修', suggest: '需确认', llm: '需大模型', manual: '需人工' }
const SEV_ORDER = { error: 0, warning: 1, info: 2 }

// 按规则分组；组内按文件列出
const groups = computed(() => {
  const m = new Map()
  for (const it of props.items) {
    if (!m.has(it.rule_id)) m.set(it.rule_id, [])
    m.get(it.rule_id).push(it)
  }
  return [...m.entries()].map(([id, list]) => ({
    id,
    rule: props.rules[id] || {},
    list,
    severity: list.reduce((a, b) => SEV_ORDER[b.severity] < SEV_ORDER[a] ? b.severity : a, 'info'),
    fixLevels: [...new Set(list.map((x) => x.fix_level))],
  })).sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || a.id.localeCompare(b.id))
})
</script>

<template>
  <p v-if="!items.length" class="notice ok">没有发现问题。</p>
  <details v-for="g in groups" :key="g.id">
    <summary class="row">
      <span class="badge" :class="g.severity">{{ SEV[g.severity] }}</span>
      <code>{{ g.id }}</code>
      <strong>{{ g.rule.title || '' }}</strong>
      <span class="muted small">{{ g.rule.category_name }}</span>
      <span class="spacer"></span>
      <span v-for="f in g.fixLevels" :key="f" class="badge" :class="f === 'auto' ? 'ok' : ''">{{ FIX[f] || f }}</span>
      <span class="muted small">{{ g.list.length }} 处</span>
    </summary>
    <table>
      <tbody>
        <tr v-for="(it, i) in g.list.slice(0, 200)" :key="i">
          <td style="width:38%" class="mono muted">{{ it.file }}</td>
          <td>{{ it.message }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="g.list.length > 200" class="muted small">仅显示前 200 条</p>
  </details>
</template>
