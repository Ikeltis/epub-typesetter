<script setup>
// 问题报告（guide/07 §6.4）：全书级问题置顶，其后按文件分组；每条问题一张卡片，带修改提示、规范条目、命中列表与豁免操作。
import { ref, computed } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  report: { type: Object, required: true },
  pid: { type: String, required: true },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['changed'])

const SEV = { error: '错误', warning: '警告', info: '提示' }
const FIX = { auto: '可自动修', suggest: '需确认', llm: '需大模型', manual: '需人工' }
const CATS = { STR: '结构', SEM: '语义', STY: '样式', TYP: '排版', TXT: '文本', RES: '资源', A11Y: '无障碍' }
const DOCS = {
  '01': '01_容器包文档与导航.md', '02': '02_内容文档与语义结构.md', '03': '03_CSS与中文排版规范.md',
  '04': '04_排版样式模板库.md', '05': '05_图片与字体资源.md', '06': '06_中文文本规范化.md', '07': '07_质检清单.md',
}
const REPO = 'https://github.com/Ikeltis/epub-typesetter/blob/main/guide/'

const sev = ref('')
const cat = ref('')
const showWaived = ref(true)
const error = ref('')

const items = computed(() => (props.report.issues || []).filter((d) =>
  (!sev.value || d.severity === sev.value)
  && (!cat.value || d.rule_id.startsWith(cat.value + '-'))
  && (showWaived.value || d.status !== 'waived')))

const groups = computed(() => {
  const m = new Map()
  for (const d of items.value) {
    const k = d.file ?? ''
    if (!m.has(k)) m.set(k, [])
    m.get(k).push(d)
  }
  return [...m.entries()].map(([file, list]) => ({ file, list }))   // 后端已按文件自然排序
})

const specHref = (s) => (DOCS[s.slice(0, 2)] ? REPO + encodeURIComponent(DOCS[s.slice(0, 2)]) : null)
const openCount = (list) => list.filter((d) => d.status !== 'waived').length

// ---------- 豁免对话框 ----------
const dlg = ref(null)          // { issue, hit, scope, reason }

function openDialog(issue, hit = null) {
  dlg.value = { issue, hit, scope: hit ? 'here' : (issue.file ? 'file' : 'book'), reason: '' }
  error.value = ''
}

function whereOf(hit) {
  if (hit.anchor) return { selector: hit.selector, anchor: hit.anchor }
  if (hit.selector && !hit.selector.startsWith('body ')) return { selector: hit.selector }
  return hit.xpath ? { xpath: hit.xpath } : null
}

async function saveWaiver() {
  const { issue, hit, scope, reason } = dlg.value
  if (!reason.trim()) return
  const w = { rule: issue.rule_id, reason: reason.trim() }
  if (scope !== 'book' && issue.file) w.file = issue.file
  if (scope === 'here' && hit) w.where = whereOf(hit)
  try {
    await api.addWaiver(props.pid, w)
    dlg.value = null
    emit('changed')
  } catch (e) { error.value = e.message }
}

async function unwaive(wid) {
  try {
    await api.removeWaiver(props.pid, wid)
    emit('changed')
  } catch (e) { error.value = e.message }
}
</script>

<template>
  <div class="row bar">
    <span class="badge error">错误 {{ report.summary.error }}</span>
    <span class="badge warning">警告 {{ report.summary.warning }}</span>
    <span class="badge">提示 {{ report.summary.info }}</span>
    <span class="badge waived">已豁免 {{ report.summary.waived }}</span>
    <span class="muted small">可自动修复 {{ report.summary.auto_fixable }}</span>
    <span class="spacer"></span>
    <select v-model="sev"><option value="">全部严重度</option><option v-for="(n, k) in SEV" :key="k" :value="k">{{ n }}</option></select>
    <select v-model="cat"><option value="">全部类别</option><option v-for="(n, k) in CATS" :key="k" :value="k">{{ n }}</option></select>
    <label class="small"><input v-model="showWaived" type="checkbox" /> 显示已豁免</label>
  </div>
  <p v-if="error" class="notice error">{{ error }}</p>
  <p v-if="!items.length" class="notice ok">没有发现问题。</p>

  <details v-for="g in groups" :key="g.file" :open="g.file === '' || items.length <= 30">
    <summary class="row">
      <strong :class="{ mono: g.file }">{{ g.file || '（全书）' }}</strong>
      <span class="spacer"></span>
      <span class="muted small">{{ openCount(g.list) }} 条<template v-if="openCount(g.list) < g.list.length">，已豁免 {{ g.list.length - openCount(g.list) }}</template></span>
    </summary>

    <div v-for="d in g.list" :key="d.key" class="issue" :class="{ waived: d.status === 'waived' }">
      <div class="row">
        <span v-if="d.status === 'waived'" class="badge waived">已豁免</span>
        <span v-else class="badge" :class="d.severity">{{ SEV[d.severity] }}</span>
        <code :title="d.title">{{ d.rule_id }}</code>
        <span>{{ d.message }}</span>
        <span v-if="d.hit_count > 1" class="muted small">{{ d.hit_count }} 处</span>
        <span v-if="d.status === 'partial' || d.status === 'skipped'" class="muted small">其中 {{ d.waived_count }} 处已豁免</span>
        <span v-if="d.status === 'skipped'" class="badge warning" title="这条规则的修复不能只避开已豁免的部分，所以整条没有修">部分豁免，未修</span>
        <span class="spacer"></span>
        <span class="badge fix" :class="d.fix_level">{{ FIX[d.fix_level] || d.fix_level }}</span>
      </div>
      <p v-if="d.hint" class="hint">{{ d.hint }}</p>
      <p v-if="d.spec.length" class="small muted">规范：
        <template v-for="(s, i) in d.spec" :key="s"><template v-if="i">、</template><a v-if="specHref(s)" :href="specHref(s)" target="_blank" rel="noopener">{{ s }}</a><span v-else>{{ s }}</span></template>
      </p>
      <p v-for="w in d.waivers" :key="w.id" class="small muted">
        豁免 {{ w.id }}：{{ w.reason }}
        <button class="link" :disabled="busy" @click="unwaive(w.id)">取消豁免</button>
      </p>
      <details v-if="d.hits.some((h) => h.xpath || h.snippet)" class="hits">
        <summary class="small muted">命中位置</summary>
        <table><tbody>
          <tr v-for="(h, i) in d.hits" :key="i" :class="{ waived: h.waived }">
            <td class="mono small loc">{{ h.line ?? h.xpath }}</td>
            <td class="mono small">{{ h.snippet }}</td>
            <td class="act">
              <span v-if="h.waived" class="badge waived">已豁免</span>
              <button v-else-if="h.xpath" class="link" :disabled="busy" @click="openDialog(d, h)">忽略此处</button>
            </td>
          </tr>
        </tbody></table>
        <p v-if="d.hits_truncated" class="muted small">另有 {{ d.hits_truncated }} 处未列出（命令行 <code>check --hits all</code> 可看全部）</p>
      </details>
      <div v-if="d.status !== 'waived' && d.rule_id !== 'STR-024'" class="row">
        <button class="small-btn" :disabled="busy" @click="openDialog(d)">忽略此问题…</button>
      </div>
    </div>
  </details>

  <div v-if="dlg" class="overlay" @click.self="dlg = null">
    <form class="card dialog" @submit.prevent="saveWaiver">
      <h3>忽略此问题</h3>
      <p class="small"><code>{{ dlg.issue.rule_id }}</code> {{ dlg.issue.message }}</p>
      <p class="small muted mono">{{ dlg.issue.file || '（全书）' }}</p>
      <fieldset>
        <label v-if="dlg.hit"><input v-model="dlg.scope" type="radio" value="here" /> 仅此处
          <span class="muted small mono">{{ dlg.hit.anchor ? `文字「${dlg.hit.anchor.quote}」` : (dlg.hit.selector || dlg.hit.xpath) }}</span></label>
        <label v-if="dlg.issue.file"><input v-model="dlg.scope" type="radio" value="file" /> 此文件内同类问题</label>
        <label><input v-model="dlg.scope" type="radio" value="book" /> 全书同类问题</label>
      </fieldset>
      <label class="small">理由（必填，供日后核对）
        <textarea v-model="dlg.reason" rows="3" placeholder="例如：作者有意在此留出空白" required></textarea>
      </label>
      <p class="muted small">被忽略的问题仍会在报告里显示为「已豁免」，下次修复时跳过对应的自动修复。</p>
      <p v-if="error" class="notice error">{{ error }}</p>
      <div class="row">
        <span class="spacer"></span>
        <button type="button" @click="dlg = null">取消</button>
        <button class="primary" type="submit" :disabled="!dlg.reason.trim()">保存</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.bar { flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.issue { padding: 10px 12px; margin: 8px 0; border: 1px solid var(--border); border-radius: var(--radius); }
.issue.waived { opacity: .6; }
.issue > p { margin: 4px 0; }
.hint { font-size: 14px; padding-left: 8px; border-left: 3px solid var(--accent); }
.badge.waived { background: var(--info-weak); color: var(--muted); }
.badge.fix.auto { background: var(--ok-weak); color: var(--ok); }
.badge.fix.suggest { background: var(--warning-weak); color: var(--warning); }
.badge.fix.llm { background: #efe6fb; color: #6f42c1; }
.hits { border-top: none; padding: 4px 0; }
tr.waived td { color: var(--muted); }
.loc { width: 1%; white-space: nowrap; }
.act { width: 1%; white-space: nowrap; text-align: right; }
button.link { border: none; background: none; padding: 0 4px; color: var(--accent); font-size: 13px; cursor: pointer; }
.small-btn { font-size: 13px; padding: 2px 10px; }
.overlay { position: fixed; inset: 0; background: rgb(0 0 0 / .35); display: flex; align-items: center; justify-content: center; z-index: 10; }
.dialog { width: min(520px, 92vw); display: flex; flex-direction: column; gap: 8px; }
.dialog h3 { margin: 0; }
.dialog fieldset { border: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.dialog textarea { width: 100%; box-sizing: border-box; margin-top: 4px; font: inherit; }
@media (prefers-color-scheme: dark) { .badge.fix.llm { background: #2d2340; color: #c8a8ff; } }
</style>
