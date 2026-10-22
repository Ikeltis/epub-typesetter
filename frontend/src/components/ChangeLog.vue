<script setup>
import { computed } from 'vue'
const props = defineProps({ changes: { type: Array, default: () => [] }, rules: { type: Object, default: () => ({}) } })
const groups = computed(() => {
  const m = new Map()
  for (const c of props.changes) {
    if (!m.has(c.rule)) m.set(c.rule, [])
    m.get(c.rule).push(c.text)
  }
  return [...m.entries()]
})
</script>

<template>
  <p v-if="!changes.length" class="notice">没有需要自动修复的内容。</p>
  <details v-for="[rule, lines] in groups" :key="rule">
    <summary class="row">
      <code>{{ rule }}</code><strong>{{ rules[rule]?.title }}</strong>
      <span class="spacer"></span><span class="muted small">{{ lines.length }} 项</span>
    </summary>
    <ul class="small">
      <li v-for="(l, i) in lines.slice(0, 300)" :key="i">{{ l }}</li>
    </ul>
  </details>
</template>
