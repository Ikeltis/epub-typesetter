<script setup>
// 排版重建的按书选项：识别开关 + 几处外观。改动即保存，下次「生成」时生效（options.py）。
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({ pid: { type: String, required: true }, value: { type: Object, default: null } })
const emit = defineEmits(['saved'])

const schema = ref(null)
const o = ref(null)
const error = ref('')
const open = ref(false)

onMounted(async () => {
  try { schema.value = await api.optionsSchema() } catch (e) { error.value = e.message }
})
watch(() => props.value, (v) => { if (v && !o.value) o.value = JSON.parse(JSON.stringify(v)) }, { immediate: true })

// 和默认不同的项（摘要，显示在折叠标题上）
const changes = computed(() => {
  if (!schema.value || !o.value) return []
  const out = []
  for (const f of schema.value.features) if (!o.value.features[f.key]) out.push(f.off)
  for (const s of schema.value.style) {
    const v = o.value.style[s.key]
    if (v !== s.default) out.push(`${s.label}：${s.choices.find((c) => c.value === v)?.label}`)
  }
  return out
})

let timer
function save() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    try { await api.saveOptions(props.pid, o.value); error.value = ''; emit('saved') } catch (e) { error.value = e.message }
  }, 300)
}
function reset() {
  o.value = JSON.parse(JSON.stringify(schema.value.defaults))
  save()
}
</script>

<template>
  <div v-if="schema && o" class="opts">
    <a href="#" class="small" @click.prevent="open = !open">{{ open ? '▾' : '▸' }} 自定义</a>
    <span class="muted small"> {{ changes.length ? '已改：' + changes.join('、') : '全部按默认' }}</span>
    <div v-if="open" class="panel">
      <div class="col">
        <div class="muted small head">识别哪些内容（关掉的按普通段落原样保留，文字不变）</div>
        <label v-for="f in schema.features" :key="f.key" class="small">
          <input v-model="o.features[f.key]" type="checkbox" @change="save" /> {{ f.label }}
        </label>
        <div class="muted small note">标题与按章拆分是重建的基础，不能关；某个标题认错了，到确认板上改。</div>
      </div>
      <div class="col">
        <div class="muted small head">外观（在统一主题上调整）</div>
        <label v-for="s in schema.style" :key="s.key" class="small styl">
          <span>{{ s.label }}</span>
          <select v-model="o.style[s.key]" @change="save">
            <option v-for="c in s.choices" :key="c.value" :value="c.value">{{ c.label }}{{ c.value === s.default ? '（默认）' : '' }}</option>
          </select>
        </label>
      </div>
      <div class="row foot">
        <span class="muted small">改动已自动保存，点「生成」后生效，并写进版本说明。</span>
        <span class="spacer"></span>
        <button v-if="changes.length" class="small-btn" @click="reset">恢复默认</button>
      </div>
      <p v-if="error" class="notice error small">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.opts { margin-top: 2px; }
.panel { display: flex; flex-wrap: wrap; gap: 10px 32px; margin-top: 8px; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: var(--radius); }
.col { display: flex; flex-direction: column; gap: 5px; min-width: 260px; flex: 1; }
.head { margin-bottom: 2px; }
.note { margin-top: 4px; }
.styl { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.foot { flex-basis: 100%; }
.small-btn { font-size: 13px; padding: 2px 10px; }
</style>
