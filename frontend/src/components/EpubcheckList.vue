<script setup>
defineProps({ report: Object })
const TONE = { FATAL: 'error', ERROR: 'error', WARNING: 'warning' }
const NAME = { FATAL: '致命', ERROR: '错误', WARNING: '警告', USAGE: '用法', INFO: '信息' }
</script>

<template>
  <p v-if="!report || !report.available" class="notice">epubcheck 不可用，只显示本工具的检查结果。</p>
  <p v-else-if="!report.messages.length" class="notice ok">epubcheck 未报告任何问题。</p>
  <table v-else>
    <thead><tr><th style="width:70px">级别</th><th style="width:90px">代码</th><th>说明</th><th style="width:60px">处数</th></tr></thead>
    <tbody>
      <tr v-for="(m, i) in report.messages" :key="i" :title="m.locations.join('\n')">
        <td><span class="badge" :class="TONE[m.severity]">{{ NAME[m.severity] || m.severity }}</span></td>
        <td class="mono">{{ m.id }}</td>
        <td>{{ m.message }}<div class="mono muted small">{{ m.locations[0] }}</div></td>
        <td class="mono">{{ m.count }}</td>
      </tr>
    </tbody>
  </table>
</template>
