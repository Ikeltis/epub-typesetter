<script setup>
// 一个预览框：选版本、选章节，像阅读器一样渲染包里的真实文件。外观（屏宽、日夜、字号）由父组件统一给。
import { ref, watch, computed } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  pid: { type: String, required: true },
  options: { type: Array, required: true },          // [{ value: 'v3', label: '版本 3 …' }, …]
  modelValue: { type: String, required: true },      // 当前版本
  width: { type: Number, default: 375 },
  height: { type: Number, default: 667 },
  theme: { type: String, default: 'day' },
  fontScale: { type: Number, default: 100 },
  start: { type: Number, default: 0 },          // 初始章节序号
})
const emit = defineEmits(['update:modelValue'])

const spine = ref([])
const idx = ref(props.start)
const error = ref('')
const frame = ref(null)
const current = ref('')          // 预览框里实际打开的包内路径（点书里的链接后会变）

const base = computed(() => `/api/books/${props.pid}/view/${props.modelValue}/`)
const src = computed(() => spine.value[idx.value] ? base.value + encodePath(spine.value[idx.value].path) : 'about:blank')
const encodePath = (p) => p.split('/').map(encodeURIComponent).join('/')

async function loadSpine() {
  error.value = ''
  try {
    const keep = spine.value[idx.value]?.title
    spine.value = await api.spine(props.pid, props.modelValue)
    // 换版本时尽量停在同名章节
    const i = keep ? spine.value.findIndex((s) => s.title === keep) : -1
    idx.value = i >= 0 ? i : Math.min(idx.value, Math.max(0, spine.value.length - 1))
  } catch (e) { spine.value = []; error.value = e.message }
}
watch(() => props.modelValue, loadSpine, { immediate: true })

// 模拟阅读器：页边距、强制改色（夜间、护眼）、字号缩放
const THEMES = {
  day: '',
  night: `html, body { background: #121212 !important; }
    body, body *:not(img):not(svg):not(image) { color: #dcdcdc !important; background-color: transparent !important; border-color: #555 !important; }
    a, a * { color: #8ab4f8 !important; }`,
  sepia: `html, body { background: #f4ecd8 !important; }
    body, body *:not(img):not(svg):not(image) { color: #5b4636 !important; background-color: transparent !important; }`,
}
function inject() {
  const doc = frame.value?.contentDocument
  if (!doc || !doc.documentElement) return
  const path = decodeURIComponent((frame.value.contentWindow.location.pathname || '').split(`/view/${props.modelValue}/`)[1] || '')
  current.value = path
  const i = spine.value.findIndex((s) => s.path === path)
  if (i >= 0 && i !== idx.value) idx.value = i
  let st = doc.getElementById('__preview__')
  if (!st) {
    st = doc.createElementNS('http://www.w3.org/1999/xhtml', 'style')
    st.id = '__preview__'
    ;(doc.head || doc.documentElement).appendChild(st)
  }
  st.textContent = `html { font-size: ${props.fontScale}% !important; padding: 12px 16px; box-sizing: border-box; }
    ${THEMES[props.theme] || ''}`
}
watch(() => [props.theme, props.fontScale], inject)

const prev = () => { if (idx.value > 0) idx.value-- }
const next = () => { if (idx.value < spine.value.length - 1) idx.value++ }
</script>

<template>
  <div class="pane">
    <div class="row bar">
      <select :value="modelValue" @change="emit('update:modelValue', $event.target.value)">
        <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
    </div>
    <div class="row bar">
      <button :disabled="idx === 0" @click="prev">‹</button>
      <select v-model.number="idx" class="chapter">
        <option v-for="(s, i) in spine" :key="s.path" :value="i">{{ i + 1 }}. {{ s.title }}</option>
      </select>
      <button :disabled="idx >= spine.length - 1" @click="next">›</button>
    </div>
    <p v-if="error" class="notice error small">{{ error }}</p>
    <div class="screen" :class="theme" :style="{ width: width ? width + 'px' : '100%', height: height + 'px' }">
      <iframe ref="frame" :src="src" sandbox="allow-same-origin" title="预览" @load="inject"></iframe>
    </div>
    <div class="muted small mono path">{{ current }}</div>
  </div>
</template>

<style scoped>
.pane { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.bar { gap: 6px; }
.bar select { max-width: 100%; }
.chapter { flex: 1; min-width: 0; }
.screen { border: 10px solid #2b2b2b; border-radius: 18px; background: #fff; overflow: hidden; max-width: 100%; }
.screen.night { background: #121212; }
.screen.sepia { background: #f4ecd8; }
iframe { width: 100%; height: 100%; border: 0; display: block; }
.path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
