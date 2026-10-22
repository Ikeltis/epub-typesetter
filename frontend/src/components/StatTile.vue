<script setup>
defineProps({ label: String, value: [String, Number], sub: String, tone: String })
</script>

<template>
  <div class="tile" :class="tone">
    <div class="tile-label">{{ label }}</div>
    <div class="tile-value">{{ value }}</div>
    <div v-if="sub" class="tile-sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.tile { flex: 1 1 180px; padding: 14px 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
.tile-label { color: var(--muted); font-size: 13px; }
.tile-value { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; line-height: 1.3; margin-top: 2px; }
.tile-sub { color: var(--muted); font-size: 12.5px; margin-top: 2px; }
.tile.error .tile-value { color: var(--error); }
.tile.ok .tile-value { color: var(--ok); }
</style>
