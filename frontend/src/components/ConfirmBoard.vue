<script setup>
// 语义确认板：上次排版重建时程序做的判断，用户改完点「按确认结果重新生成」（board.py）。
import { ref, computed, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({ pid: { type: String, required: true }, busy: Boolean, stamp: { type: Number, default: 0 } })
const emit = defineEmits(['rebuild', 'started'])

const data = ref(null)
const error = ref('')
const saving = ref(false)
const d = ref({ clusters: {}, kinds: {}, items: {}, heads: {}, matter: {} })   // 正在编辑的决定
const open = ref({})                                     // 展开的结构类别
const showSmall = ref(false)

async function load() {
  try {
    data.value = await api.board(props.pid)
    d.value = { heads: {}, matter: {}, ...JSON.parse(JSON.stringify(data.value.decisions)) }
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
  + Object.keys(d.value.items).length + Object.keys(d.value.heads).length + Object.keys(d.value.matter).length)

// ---- 标题层级与辅文 ----
const HEAD_KINDS = [['part', '部'], ['chapter', '章'], ['section', '节'], ['subsection', '小节'], ['para', '不是标题']]
const MATTER = [['', '正文章节'], ['preface', '前言/序'], ['foreword', '他序'], ['introduction', '导言'], ['prologue', '楔子'],
  ['epilogue', '尾声'], ['afterword', '后记/跋'], ['acknowledgments', '致谢'], ['appendix', '附录'],
  ['bibliography', '参考文献'], ['glossary', '术语表'], ['dedication', '献辞'], ['epigraph', '题词'], ['copyright', '版权页']]
const headLabel = (k) => HEAD_KINDS.find((x) => x[0] === k)?.[1] || k
const matterLabel = (k) => MATTER.find((x) => x[0] === k)?.[1] || k
const headKind = (h) => d.value.heads[h.key] ?? h.kind
const headMatter = (h) => d.value.matter[h.key] ?? h.matter
function setHead(h, v) { if (v === h.kind && !h.decided) delete d.value.heads[h.key]; else d.value.heads[h.key] = v }
function setMatter(h, v) { if (v === h.matter && !h.decided_matter) delete d.value.matter[h.key]; else d.value.matter[h.key] = v }
const headDiffers = (h) => h.llm && (h.llm.kind !== headKind(h) || (h.llm.matter || '') !== (headMatter(h) || ''))
function adoptHead(h) { if (h.llm) { setHead(h, h.llm.kind); if (h.llm.matter || headMatter(h)) setMatter(h, h.llm.matter || '') } }
const showHeads = ref(false)
const headsShown = computed(() => (data.value?.heads || []).filter((h) => showHeads.value || h.llm || h.key in d.value.heads || h.key in d.value.matter))

async function save() {
  saving.value = true
  try {
    await api.saveDecisions(props.pid, d.value)
    emit('rebuild')
  } catch (e) { error.value = e.message } finally { saving.value = false }
}
function reset() { d.value = { clusters: {}, kinds: {}, items: {}, heads: {}, matter: {} } }

// ---- 大模型 ----
const llmTasks = ref({ clusters: true, structures: true, heads: true })
const roleLabel = (r) => data.value?.roles.find((x) => x.value === r)?.label || r
const pct = (c) => `${Math.round(c * 100)}%`
async function runLlm() {
  error.value = ''
  try {
    await api.runLlm(props.pid, Object.keys(llmTasks.value).filter((k) => llmTasks.value[k]))
    emit('started')
  } catch (e) { error.value = e.message }
}
// 采纳：把大模型的判断写进待保存的决定（仍要点「按确认结果重新生成」）
function adoptCluster(c) { if (c.llm && c.llm.role !== 'other') setCluster(c, c.llm.role) }
function adoptItem(k, it) { if (it.llm) toggleItem(k, it, it.llm.accept) }
function adoptSugg(s) { if (s.llm) toggleSugg(s, s.llm.accept) }
const clusterDiffers = (c) => c.llm && c.llm.role !== 'other' && c.llm.role !== clusterRole(c)
const itemDiffers = (k, it) => it.llm && it.llm.accept !== itemOn(k, it)
const suggDiffers = (s) => s.llm && s.llm.accept !== suggOn(s)
const pending = computed(() => {
  if (!data.value?.llm) return 0
  let n = data.value.clusters.filter(clusterDiffers).length
  for (const k of data.value.structures) n += k.items.filter((it) => itemDiffers(k, it)).length
  n += (data.value.heads || []).filter(headDiffers).length
  return n + actionable.value.filter(suggDiffers).length
})
function adoptAll(min = 0.8) {
  for (const c of data.value.clusters) if (clusterDiffers(c) && c.llm.confidence >= min) adoptCluster(c)
  for (const k of data.value.structures) for (const it of k.items) if (itemDiffers(k, it) && it.llm.confidence >= min) adoptItem(k, it)
  for (const s of actionable.value) if (suggDiffers(s) && s.llm.confidence >= min) adoptSugg(s)
  for (const h of data.value.heads || []) if (headDiffers(h) && h.llm.confidence >= min) adoptHead(h)
}
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

    <div class="llm card-lite">
      <div class="row">
        <strong>大模型分析</strong>
        <label class="small"><input v-model="llmTasks.clusters" type="checkbox" /> 段落样式</label>
        <label class="small"><input v-model="llmTasks.structures" type="checkbox" /> 结构与建议</label>
        <label class="small" title="用重型模型，一次看全书标题"><input v-model="llmTasks.heads" type="checkbox" /> 标题层级与辅文</label>
        <span class="spacer"></span>
        <button :disabled="busy || !Object.values(llmTasks).some(Boolean)" @click="runLlm">{{ data.llm ? '重新分析' : '开始分析' }}</button>
        <a href="#/settings" class="small">设置</a>
      </div>
      <p class="muted small">会把每组、每处的几段样例（不是整本书）发给大模型；同样的内容只问一次。大模型只给建议，点「采纳」后才写进决定。</p>
      <template v-if="data.llm">
        <p class="small">
          {{ data.llm.models?.light }} / {{ data.llm.models?.heavy }}：调用 {{ data.llm.usage.calls }} 次，命中缓存 {{ data.llm.usage.cached }} 次<template v-if="data.llm.usage.blocked">，被接口方内容审核拦下 {{ data.llm.usage.blocked }} 条</template><template v-if="data.llm.usage.refused">，拒答 {{ data.llm.usage.refused }} 条</template>；
          按官方价估算约 ${{ data.llm.usage.cost.toFixed(4) }}<span class="muted">（{{ data.llm.base_url }}，走中转时以中转计费为准）</span>
        </p>
        <p v-for="(e, i) in data.llm.errors" :key="i" class="notice error small">{{ e }}</p>
        <div v-if="pending" class="row">
          <span class="small">大模型的意见与当前决定不同的有 {{ pending }} 处。</span>
          <button @click="adoptAll(0.8)">采纳置信度 ≥ 80% 的</button>
          <button @click="adoptAll(0)">全部采纳</button>
        </div>
      </template>
    </div>

    <h3>段落样式（{{ data.clusters.length }} 组）</h3>
    <p class="muted small">原书样式相同的段落归为一组，可以整组改成别的角色。只列 3 段以上的组<template v-if="hiddenClusters">，另有 {{ hiddenClusters }} 个零散小组
      <a href="#" @click.prevent="showSmall = true">显示</a></template>。</p>
    <table class="clusters">
      <thead><tr><th>样例</th><th>原样式</th><th>段数</th><th>角色</th><th v-if="data.llm">大模型</th></tr></thead>
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
          <td v-if="data.llm" class="small llm-cell">
            <template v-if="c.llm">
              <span :title="c.llm.reason">{{ c.llm.role === 'other' ? '保持原判' : roleLabel(c.llm.role) }} <span class="muted">{{ pct(c.llm.confidence) }}</span></span>
              <button v-if="clusterDiffers(c)" class="link" @click="adoptCluster(c)">采纳</button>
              <div class="muted reason">{{ c.llm.reason }}</div>
            </template>
            <span v-else class="muted">—</span>
          </td>
        </tr>
      </tbody>
    </table>

    <h3>标题（{{ data.heads?.length || 0 }} 个）</h3>
    <p class="muted small">决定每个标题的级别，以及章一级的辅文类型（前言、后记等，影响语义标注和导航）。
      默认只列大模型有意见或你改过的；<a href="#" @click.prevent="showHeads = !showHeads">{{ showHeads ? '只看有意见的' : '列出全部标题' }}</a>。</p>
    <table v-if="headsShown.length" class="items"><tbody>
      <tr v-for="h in headsShown.slice(0, 600)" :key="h.key" :class="{ changed: h.key in d.heads || h.key in d.matter }">
        <td>{{ h.text }}</td>
        <td class="small muted mono">{{ h.doc }}</td>
        <td><select :value="headKind(h)" @change="setHead(h, $event.target.value)">
          <option v-for="[v, l] in HEAD_KINDS" :key="v" :value="v">{{ l }}</option></select></td>
        <td><select v-if="['chapter', 'part'].includes(headKind(h))" :value="headMatter(h)" @change="setMatter(h, $event.target.value)">
          <option v-for="[v, l] in MATTER" :key="v" :value="v">{{ l }}</option></select></td>
        <td v-if="data.llm" class="small llm-cell">
          <template v-if="h.llm">
            {{ headLabel(h.llm.kind) }}<template v-if="h.llm.matter"> · {{ matterLabel(h.llm.matter) }}</template>
            <span class="muted">{{ pct(h.llm.confidence) }}</span>
            <button v-if="headDiffers(h)" class="link" @click="adoptHead(h)">采纳</button>
            <div class="muted reason">{{ h.llm.reason }}</div>
          </template>
        </td>
      </tr>
    </tbody></table>

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
          <td v-if="data.llm" class="small llm-cell">
            <template v-if="it.llm">
              <span :class="it.llm.accept ? 'ok-text' : 'warn-text'">{{ it.llm.accept ? '成立' : '不成立' }}</span> <span class="muted">{{ pct(it.llm.confidence) }}</span>
              <button v-if="itemDiffers(k, it)" class="link" @click="adoptItem(k, it)">采纳</button>
              <div class="muted reason">{{ it.llm.reason }}</div>
            </template>
          </td>
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
          <td v-if="data.llm" class="small llm-cell">
            <template v-if="s.llm">
              <span :class="s.llm.accept ? 'ok-text' : 'warn-text'">{{ s.llm.accept ? '建议执行' : '不建议' }}</span> <span class="muted">{{ pct(s.llm.confidence) }}</span>
              <button v-if="suggDiffers(s)" class="link" @click="adoptSugg(s)">采纳</button>
              <div class="muted reason">{{ s.llm.reason }}</div>
            </template>
          </td>
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
tr.off td.llm-cell { opacity: 1; }
.card-lite { border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; margin: 10px 0; }
.card-lite p { margin: 6px 0; }
.llm-cell { width: 22%; }
.reason { font-size: 12px; line-height: 1.4; }
.ok-text { color: var(--ok); }
.warn-text { color: var(--warning); }
button.link { border: none; background: none; padding: 0 4px; color: var(--accent); cursor: pointer; font-size: 13px; }
.badge { margin-left: 6px; }
</style>
