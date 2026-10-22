<script setup>
import { computed } from 'vue'
import { STATUS, BUSY } from '../api.js'
const props = defineProps({ status: String })
const tone = computed(() => props.status === 'error' ? 'error'
  : props.status === 'fixed' ? 'ok' : BUSY.has(props.status) ? 'busy' : '')
</script>

<template>
  <span class="badge" :class="tone">
    <span v-if="BUSY.has(status)" class="spinner" style="width:10px;height:10px;vertical-align:-1px"></span>
    {{ STATUS[status] || status }}
  </span>
</template>
