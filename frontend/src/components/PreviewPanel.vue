<script setup>
// 实时预览：屏宽、日夜、字号统一设置；可并排对比两个版本（默认左原件、右最新版本）。
import { ref, computed, watch } from 'vue'
import PreviewPane from './PreviewPane.vue'

const props = defineProps({
  pid: { type: String, required: true },
  versions: { type: Array, default: () => [] },
  want: { type: String, default: '' },              // 外部指定要看的版本（下载列表里点「预览」）
})

const DEVICES = { phone: [375, 667, '手机'], tablet: [768, 1024, '平板'], desktop: [0, 800, '桌面'] }
// 设置记在浏览器里；地址栏 ?device=&theme=&font=&compare=1&chapter= 可覆盖（便于分享、收藏某个预览）
const saved = JSON.parse(localStorage.getItem('preview') || '{}')
const q = new URLSearchParams(location.search)
const device = ref(q.get('device') || saved.device || 'phone')
const theme = ref(q.get('theme') || saved.theme || 'day')
const fontScale = ref(Number(q.get('font') || saved.fontScale || 100))
const compare = ref(q.has('compare') ? q.get('compare') === '1' : !!saved.compare)
const startChapter = Number(q.get('chapter') || 0)
watch([device, theme, fontScale, compare], () => localStorage.setItem('preview', JSON.stringify(
  { device: device.value, theme: theme.value, fontScale: fontScale.value, compare: compare.value })))

const options = computed(() => [
  ...props.versions.map((v, i) => ({ value: 'v' + v.n, label: `版本 ${v.n}${i === 0 ? '（最新）' : ''}` })),
  { value: 'original', label: '原件' },
])
const right = ref(props.want || (props.versions[0] ? 'v' + props.versions[0].n : 'original'))
const left = ref('original')
watch(() => props.want, (w) => { if (w) right.value = w })
watch(() => props.versions[0]?.n, (n, old) => { if (n && right.value === (old ? 'v' + old : 'original')) right.value = 'v' + n })

const size = computed(() => DEVICES[device.value])
</script>

<template>
  <div class="row controls">
    <span class="muted small">屏宽</span>
    <div class="seg"><button v-for="(d, k) in DEVICES" :key="k" :class="{ on: device === k }" @click="device = k">{{ d[2] }}</button></div>
    <span class="muted small">显示</span>
    <div class="seg">
      <button :class="{ on: theme === 'day' }" @click="theme = 'day'">日间</button>
      <button :class="{ on: theme === 'night' }" @click="theme = 'night'">夜间</button>
      <button :class="{ on: theme === 'sepia' }" @click="theme = 'sepia'">护眼</button>
    </div>
    <span class="muted small">字号</span>
    <div class="seg">
      <button @click="fontScale = Math.max(70, fontScale - 10)">A−</button>
      <button class="mono" @click="fontScale = 100">{{ fontScale }}%</button>
      <button @click="fontScale = Math.min(200, fontScale + 10)">A+</button>
    </div>
    <label class="small"><input v-model="compare" type="checkbox" /> 并排对比</label>
  </div>
  <p class="muted small">直接打开书里的章节文件渲染，和阅读器看到的一致。夜间、护眼模拟阅读器的强制改色；书里专为系统夜间模式写的样式以实机为准。暂为滚动阅读，不模拟翻页。</p>
  <div class="panes" :class="{ two: compare }">
    <PreviewPane v-if="compare" v-model="left" :pid="pid" :options="options" :width="size[0]" :height="size[1]"
                 :theme="theme" :font-scale="fontScale" :start="startChapter" />
    <PreviewPane v-model="right" :pid="pid" :options="options" :width="size[0]" :height="size[1]"
                 :theme="theme" :font-scale="fontScale" :start="startChapter" />
  </div>
</template>

<style scoped>
.controls { gap: 8px 10px; flex-wrap: wrap; margin-bottom: 4px; }
.seg { display: inline-flex; }
.seg button { border-radius: 0; margin-left: -1px; padding: 3px 10px; font-size: 13px; }
.seg button:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
.seg button:last-child { border-radius: 0 6px 6px 0; }
.seg button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.panes { display: flex; gap: 20px; overflow-x: auto; padding-bottom: 6px; }
.panes > * { flex: 0 1 auto; }
.panes:not(.two) > * { margin: 0 auto; }
</style>
