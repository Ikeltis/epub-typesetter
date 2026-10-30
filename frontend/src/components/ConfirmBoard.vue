<script setup>
// 语义确认板：上次排版重建时程序做的判断，用户改完点「按确认结果重新生成」（board.py）。
import { ref, computed, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({ pid: { type: String, required: true }, busy: Boolean, stamp: { type: Number, default: 0 } })
const emit = defineEmits(['rebuild'])

const data = ref(null)
const error = ref('')
const saving = ref(false)
const d = ref({ clusters: {}, kinds: {}, items: {} })   // 正在编辑的决定
const open = ref({})                                     // 展开的结构类别
const showSmall = ref(false)

async function load() {
  try {
    data.value = await api.board(props.pid)
    d.value = JSON.parse(JSON.stringify(data.value.decisions))
    error.value = ''
  } catch (e) { data.value = null; error.value = e.message }
}
watch(() => props.stamp, load, { immediate: true })

const clusters = computed(() => (data.value?.clusters || []).filter((c) => showSmall.value || c.count >= 3 || c.body || c.decided))
const hiddenClusters = computed(() => (data.value?.clusters || []).length - clusters.value.length)

// ---- 簇 ----
const clusterRole = (c) => d.value.clusters[c.key] ?? c.role
function setCluster(c, role) {
  if (role === c.role && !c.decided) delete d.value.clusters[c.key]
  else d.value.clusters[c.key] = role
}

// ---- 结构 ----
function kindOn(k) { return d.value.kinds[k.kind] ?? true }
function itemOn(k, it) { return d.value.items[it.key] ?? kindOn(k) }
function toggleKind(k, on) {
  d.value.kinds[k.kind] = on
  for (const it of k.items) delete d.value.items[it.key]          // 整类设定覆盖逐条
}
function toggleItem(k, it, on) {
  if (on === kindOn(k)) delete d.value.items[it.key]
  else d.value.items[it.key] = on
}
const offCount = (k) => k.items.filter((it) => !itemOn(k, it)).length

// ---- 建议 ----
const actionable = computed(() => (data.value?.suggestions || []).filter((s) => s.actionable))
const notes = computed(() => (data.value?.suggestions || []).filter((s) => !s.actionable))
const suggOn = (s) => d.value.items[s.key] ?? false
function toggleSugg(s, on) {
  if (on) d.value.items[s.key] = true
  else delete d.value.items[s.key]
}

const dirty = computed(() => data.value && JSON.stringify(d.value) !== JSON.stringify(data.value.decisions))
const changed = computed(() => Object.keys(d.value.clusters).length + Object.keys(d.value.kinds).length
  + Object.keys(d.value.items).length)

async function save() {
  saving.value = true
  try {
    await api.saveDecisions(props.pid, d.value)
    emit('rebuild')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}
function reset() { d.value = { clusters: {}, kinds: {}, items: {} } }
</script>

<template>
  <p v-if="error" class="notice">{{ error }}</p>
  <template v-if="data">
    <div class="row bar">
      <p class="muted small" style="margin:0; flex:1">
        这里是上次排版重建时程序替你做的判断。改完点「按确认结果重新生成」；决定会保存，以后重建都按它来。
        A：原书已标明；B：按规范的识别信号自动改写；C：把握不够，默认不改。
      </p>
      <button :disabled="busy || !changed" @click="reset" title="清空所有决定，回到程序默认">恢复默认</button>
      <button class="primary" :disabled="busy || saving || (!dirty && !changed)" @click="save">按确认结果重新生成</button>
    </div>

    <h3>段落样式（{{ data.clusters.length }} 组）</h3>
    <p class="muted small">原书样式相同的段落归为一组，可以整组改成别的角色。只列 3 段以上的组<template v-if="hiddenClusters">，另有 {{ hiddenClusters }} 个零散小组
      <a href="#" @click.prevent="showSmall = true">显示</a></template>。</p>
    <table class="clusters">
      <thead><tr><th>样例</th><th>原样式</th><th>段数</th><th>角色</th></tr></thead>
      <tbody>
        <tr v-for="c in clusters" :key="c.key" :class="{ changed: c.key in d.clusters }">
          <td><div v-for="(s, i) in c.samples" :key="i" class="sample">{{ s.text }}</div></td>
          <td class="small muted">{{ c.style }}<span v-if="c.body" class="badge ok">正文主流</span></td>
          <td class="mono">{{ c.count }}</td>
          <td>
            <select :value="clusterRole(c)" @change="setCluster(c, $event.target.value)">
              <option v-for="r in data.roles" :key="r.value" :value="r.value">{{ r.label }}</option>
              <option v-if="!data.roles.some((r) => r.value === c.role)" :value="c.role">{{ c.role }}</option>
            </select>
          </td>
        </tr>
      </tbody>
    </table>

    <h3>识别出的结构</h3>
    <p v-if="!data.structures.length" class="muted small">这本书没有识别出诗歌、书信、列表等结构。</p>
    <div v-for="k in data.structures" :key="k.kind" class="kind">
      <div class="row">
        <label><input type="checkbox" :checked="kindOn(k)" @change="toggleKind(k, $event.target.checked)" />
          <strong>{{ k.label }}</strong></label>
        <span class="muted small">{{ k.total }} 处（<template v-for="(n, lv, i) in k.levels" :key="lv"><template v-if="i">、</template>{{ lv }} 级 {{ n }}</template>）</span>
        <span v-if="offCount(k)" class="badge warning">{{ offCount(k) }} 处不改写</span>
        <span class="spacer"></span>
        <a href="#" @click.prevent="open[k.kind] = !open[k.kind]">{{ open[k.kind] ? '收起' : '逐条查看' }}</a>
      </div>
      <table v-if="open[k.kind]" class="items"><tbody>
        <tr v-for="it in k.items.slice(0, 300)" :key="it.key" :class="{ off: !itemOn(k, it) }">
          <td class="chk"><input type="checkbox" :checked="itemOn(k, it)" @change="toggleItem(k, it, $event.target.checked)" /></td>
          <td class="mono small muted">{{ it.level }}</td>
          <td><div v-for="(l, i) in it.lines" :key="i" class="sample">{{ l }}</div>
            <span v-if="it.count > it.lines.length" class="muted small">…共 {{ it.count }} 段</span></td>
          <td class="small muted mono">{{ it.doc }}</td>
        </tr>
      </tbody></table>
      <p v-if="open[k.kind] && k.items.length > 300" class="muted small">只列前 300 处；可用上面的整类开关一次处理全部。</p>
    </div>

    <template v-if="actionable.length">
      <h3>建议（C 级，默认不改）</h3>
      <table class="items"><tbody>
        <tr v-for="s in actionable" :key="s.key" :class="{ off: !suggOn(s) }">
          <td class="chk"><input type="checkbox" :checked="suggOn(s)" @change="toggleSugg(s, $event.target.checked)" /></td>
          <td style="width:90px"><span class="badge">{{ s.label }}</span></td>
          <td class="small">{{ s.text }}<div v-for="(l, i) in s.lines" :key="i" class="sample muted">{{ l }}</div></td>
          <td class="small muted mono">{{ s.doc }}</td>
        </tr>
      </tbody></table>
    </template>
    <template v-if="notes.length">
      <h3>提示</h3>
      <ul class="small muted"><li v-for="(s, i) in notes" :key="i">{{ s.text }}</li></ul>
    </template>
  </template>
</template>

<style scoped>
.bar { gap: 8px; align-items: flex-start; margin-bottom: 4px; }
h3 { margin: 18px 0 6px; }
.sample { font-size: 13px; line-height: 1.5; max-width: 52em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.clusters td:first-child { max-width: 0; width: 55%; }
tr.changed td { background: var(--accent-weak); }
.kind { border-top: 1px solid var(--border); padding: 8px 0; }
.items td:nth-child(3) { max-width: 0; width: 70%; }
.chk { width: 1%; }
tr.off td { opacity: .5; }
.badge { margin-left: 6px; }
</style>
