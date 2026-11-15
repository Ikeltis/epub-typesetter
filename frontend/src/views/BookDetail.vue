<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api, BUSY } from '../api.js'
import StatusBadge from '../components/StatusBadge.vue'
import IssueReport from '../components/IssueReport.vue'
import EpubcheckList from '../components/EpubcheckList.vue'
import ChangeLog from '../components/ChangeLog.vue'
import ConfirmBoard from '../components/ConfirmBoard.vue'
import PreviewPanel from '../components/PreviewPanel.vue'

const props = defineProps({ id: String, initialTab: { type: String, default: '' } })
const data = ref(null)
const rules = ref({})
const error = ref('')
// 工作区：左侧导航选主区内容，预览是可随时开关的右侧面板。
// 旧地址 #/book/<id>/preview 仍有效：打开预览面板。没指定时，有确认板就进确认板，否则进概况
const TABS = ['overview', 'board', 'issues', 'changes', 'epubcheck', 'rebuild']
const tab = ref(TABS.includes(props.initialTab) ? props.initialTab : '')
const previewOpen = ref(props.initialTab === 'preview' || localStorage.getItem('previewOpen') === '1')
watch(previewOpen, (v) => localStorage.setItem('previewOpen', v ? '1' : '0'))
// 当前标签页写进地址，刷新后停在原处
watch(tab, (t) => { if (t) history.replaceState(null, '', `#/book/${props.id}/${t}`) })
let timer

const meta = computed(() => data.value?.meta)
const audit = computed(() => data.value?.audit)
const fix = computed(() => data.value?.fix)
const busy = computed(() => meta.value && BUSY.has(meta.value.status))
const autoCount = computed(() => audit.value?.issues.summary?.auto_fixable ?? 0)
const versions = computed(() => data.value?.versions || [])
const sum = computed(() => data.value?.summary)
const mode = ref('rebuild')
const open = ref({})
const viewOriginal = ref(false)
const shownIssues = computed(() => (fix.value && !viewOriginal.value ? fix.value.after : audit.value.issues))
// 已保存的决定还没进最新版本：最新版本不是重建，或它用的决定数与现在不同，或保存后还没重新生成
const pendingDecisions = computed(() => {
  const v = versions.value[0]
  if (!sum.value?.board || !sum.value.decisions.total && !fix.value?.decisions_changed) return false
  return !!fix.value?.decisions_changed || !v || v.mode !== 'rebuild' || v.decisions !== sum.value.decisions.total
})
function versionLabel(v) {
  if (v.mode !== 'rebuild') return '仅规范修复'
  if (!v.decisions) return '排版重建（程序默认）'
  return `排版重建 + ${v.decisions} 处确认` + (v.llm ? `（含大模型意见 ${v.llm} 处）` : '')
}
const when = (t) => new Date(t * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const previewWant = ref('')
function preview(which) {
  previewWant.value = which
  previewOpen.value = true
}
function openTab(t) {
  tab.value = t
  viewOriginal.value = false
  window.scrollTo({ top: 0 })
}
function showOriginal() {
  viewOriginal.value = true
  tab.value = 'issues'
  window.scrollTo({ top: 0 })
}
// 顶栏的主按钮：确认板上有没保存或还没生成进书的决定时，就是「按确认结果重新生成」
const board = ref(null)
const boardDirty = computed(() => !!board.value?.unsaved)
const needRegen = computed(() => boardDirty.value || pendingDecisions.value)
function regenerate() {
  if (boardDirty.value) board.value.save()          // 先存决定，存完由确认板触发重建
  else runFix('rebuild', true)
}
const latestIssues = computed(() => (fix.value ? fix.value.after.total : audit.value?.issues.total))

async function load() {
  try {
    data.value = await api.book(props.id)
    error.value = ''
    if (!tab.value && data.value.audit) tab.value = data.value.fix?.rebuild ? 'board' : 'overview'
  } catch (e) { error.value = e.message }
  clearTimeout(timer)
  if (busy.value) timer = setTimeout(load, 1500)
}

async function runFix(mode, keepTab = false) {
  try {
    await api.fix(props.id, mode)
    if (!keepTab) tab.value = mode === 'rebuild' ? 'board' : 'changes'
    viewOriginal.value = false
    await load()
  } catch (e) { error.value = e.message }
}

async function remove() {
  if (!confirm('删除这本书的原件和所有处理结果？')) return
  await api.remove(props.id)
  location.hash = '#/'
}

const sevCount = (rep, s) => rep?.summary?.[s] || 0
const epcCount = (r) => (r?.available ? `${r.blocking} 个错误` : '未校验')
const kb = (n) => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`

onMounted(async () => {
  load()
  try {
    rules.value = Object.fromEntries((await api.rules()).map((r) => [r.id, r]))
  } catch { /* 规则名只用于显示 */ }
})
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <p v-if="error" class="notice error">{{ error }}</p>
  <template v-if="meta">
    <header class="bookbar">
      <div class="row top">
        <a href="#/" class="back" title="返回书库">←</a>
        <div class="tt">
          <div class="row"><h1 class="title" :title="meta.filename">{{ meta.title || meta.filename }}</h1><StatusBadge :status="meta.status" /></div>
          <div class="muted small info" :title="meta.filename">
            {{ meta.author || '作者未知' }} · EPUB {{ meta.version || '?' }}<template v-if="audit"> · {{ audit.book.documents }} 个正文文件 · {{ kb(meta.size) }}</template>
          </div>
        </div>
        <span class="spacer"></span>
        <template v-if="audit">
          <div class="row gen">
            <select v-model="mode" :disabled="busy" title="生成方式">
              <option value="rebuild">排版重建</option>
              <option value="basic">仅规范修复</option>
            </select>
            <button :class="{ primary: !needRegen }" :disabled="busy" @click="runFix(mode)">生成</button>
          </div>
          <button v-if="needRegen" class="primary" :disabled="busy" @click="regenerate"
                  :title="boardDirty ? '保存确认板上的改动并重新生成' : '已保存的决定还没生成进书里'">按确认结果重新生成</button>
          <a v-if="versions.length" class="btn" :href="api.downloadUrl(id, 'v' + versions[0].n)" :title="`下载版本 ${versions[0].n}`">下载最新</a>
          <button v-if="versions.length" :class="{ on: previewOpen }" @click="previewOpen = !previewOpen">预览</button>
        </template>
        <button class="danger quiet" :disabled="busy" title="删除这本书" @click="remove">删除</button>
      </div>
      <p v-if="busy" class="row status"><span class="spinner"></span>
        {{ meta.status === 'fixing' ? '正在修复并重新校验，较大的书需要几十秒…'
          : meta.status === 'thinking' ? (meta.message || '大模型分析中…') : '正在体检（含 epubcheck 校验）…' }}</p>
      <p v-if="meta.status === 'error'" class="notice error status">{{ meta.message }}</p>
      <p v-else-if="!busy && meta.message" class="notice status">{{ meta.message }}</p>
    </header>

    <div v-if="audit" class="workspace" :class="{ 'has-side': previewOpen && versions.length }">
      <nav class="sidenav">
        <button :class="{ active: tab === 'overview' }" @click="openTab('overview')">概况</button>
        <button v-if="fix?.rebuild" :class="{ active: tab === 'board' }" @click="openTab('board')">
          确认板<span v-if="needRegen" class="dot" title="有决定还没生成进书里"></span></button>
        <button :class="{ active: tab === 'issues' }" @click="openTab('issues')">问题清单<span class="count" :title="fix ? `最新版本剩余问题（原书 ${audit.issues.total}）` : '原书的问题'">{{ latestIssues }}</span></button>
        <button v-if="fix" :class="{ active: tab === 'changes' }" @click="openTab('changes')">修改记录<span class="count">{{ fix.changes.length }}</span></button>
        <div class="sep">更多</div>
        <button :class="{ active: tab === 'epubcheck' }" @click="openTab('epubcheck')">epubcheck</button>
        <button v-if="fix?.rebuild" :class="{ active: tab === 'rebuild' }" @click="openTab('rebuild')">重建详情</button>
      </nav>

      <div class="main">
      <section v-show="tab === 'overview'" class="card steps">
        <!-- ① 体检 -->
        <div class="step done">
          <div class="num">1</div>
          <div class="body">
            <div class="row"><strong>体检</strong><span class="muted small">原书的问题</span></div>
            <div class="small">
              epubcheck <b :class="{ bad: audit.epubcheck.blocking }">{{ audit.epubcheck.available ? audit.epubcheck.blocking : '—' }}</b> 个错误 ·
              本工具发现 <b>{{ audit.issues.total }}</b> 处问题（错误 {{ sevCount(audit.issues, 'error') }}、警告 {{ sevCount(audit.issues, 'warning') }}），其中 {{ autoCount }} 处可自动修
              <a href="#" @click.prevent="showOriginal()">查看</a>
              <template v-if="fix">；最新版本（版本 {{ versions[0]?.n }}）还剩 <b>{{ fix.after.total }}</b> 处（错误 {{ sevCount(fix.after, 'error') }}、警告 {{ sevCount(fix.after, 'warning') }}）
                <a href="#" @click.prevent="openTab('issues')">查看</a></template>
            </div>
          </div>
        </div>

        <!-- ② 生成 -->
        <div class="step" :class="{ done: versions.length }">
          <div class="num">2</div>
          <div class="body">
            <div class="row"><strong>生成</strong><span class="muted small">选一种方式，生成新的 EPUB；每次生成都会留一个版本</span></div>
            <div class="row choices">
              <label><span><input v-model="mode" type="radio" value="rebuild" /> <b>排版重建</b>（推荐）</span>
                <span class="muted small">识别标题、插图、注释、诗歌等，按规范重排，套用统一主题</span></label>
              <label><span><input v-model="mode" type="radio" value="basic" /> <b>仅规范修复</b></span>
                <span class="muted small">只修规范错误和伪排版，版面不动</span></label>
              <button class="primary" :disabled="busy" @click="runFix(mode)">生成</button>
            </div>
          </div>
        </div>

        <!-- ③ 确认 -->
        <div class="step" :class="{ done: sum?.board && !pendingDecisions, off: !sum?.board }">
          <div class="num">3</div>
          <div class="body">
            <div class="row"><strong>确认</strong><span class="muted small">检查程序的判断，可让大模型给意见；改动要「重新生成」才进书里</span></div>
            <div v-if="!sum?.board" class="small muted">做一次「排版重建」后，这里会列出程序的判断供你确认。</div>
            <template v-else>
              <div class="small">
                段落样式 {{ sum.board.clusters }} 组 · 识别出的结构 {{ sum.board.structures }} 处 · 标题 {{ sum.board.heads }} 个 · 待定建议 {{ sum.board.suggestions }} 条
              </div>
              <div class="small">
                大模型：<template v-if="sum.llm">已分析，{{ sum.llm.opinions }} 条意见<template v-if="sum.llm.cost != null">（约 ${{ sum.llm.cost.toFixed(3) }}）</template></template>
                <template v-else>还没分析</template>
                · 你的决定 {{ sum.decisions.total }} 处<template v-if="sum.decisions.llm">（其中采纳大模型意见 {{ sum.decisions.llm }} 处）</template>
              </div>
              <div class="row">
                <button @click="openTab('board')">打开确认板</button>
                <template v-if="pendingDecisions">
                  <span class="notice small">有决定还没生成进书里</span>
                  <button class="primary" :disabled="busy" @click="runFix('rebuild')">按确认结果重新生成</button>
                </template>
              </div>
            </template>
          </div>
        </div>

        <!-- ④ 下载 -->
        <div class="step" :class="{ done: versions.length, off: !versions.length }">
          <div class="num">4</div>
          <div class="body">
            <div class="row"><strong>下载</strong><span class="muted small">保留最近 5 个版本</span></div>
            <table class="versions"><tbody>
              <template v-for="(v, i) in versions" :key="v.n">
                <tr :class="{ latest: i === 0 }">
                  <td class="mono">版本 {{ v.n }}</td>
                  <td>{{ versionLabel(v) }}<span v-if="i === 0" class="badge ok">最新</span></td>
                  <td class="small muted">{{ when(v.created) }}</td>
                  <td class="small"><span :class="v.epubcheck ? 'bad' : 'good'">epubcheck {{ v.epubcheck ?? '—' }} 错</span>
                    · <span :class="v.text_ok ? 'good' : 'bad'">{{ v.text_ok ? '文字完整' : '文字有差异' }}</span></td>
                  <td class="act"><a href="#" class="small" @click.prevent="open[v.n] = !open[v.n]">详情</a>
                    <a href="#" class="small" @click.prevent="preview('v' + v.n)">预览</a>
                    <a class="btn" :class="{ primary: i === 0 }" :href="api.downloadUrl(id, 'v' + v.n)">下载</a></td>
                </tr>
                <tr v-if="open[v.n]" class="detail"><td></td><td colspan="4" class="small muted">
                  {{ v.mode === 'rebuild' ? `重建为 ${v.files} 个文件，注释 ${v.notes} 条；` : '' }}剩余问题 {{ v.issues }} 处；{{ v.text }}；{{ kb(v.size) }}
                  <template v-if="v.mode === 'rebuild'">；用了 {{ v.decisions }} 处确认板上的决定<template v-if="v.llm">，其中 {{ v.llm }} 处与大模型意见一致</template></template>
                </td></tr>
              </template>
              <tr>
                <td class="mono">原件</td><td class="muted">上传的原书，未改动</td><td></td><td></td>
                <td class="act"><a href="#" class="small" @click.prevent="preview('original')">预览</a>
                  <a class="btn" :href="api.downloadUrl(id, 'original')">下载</a></td>
              </tr>
            </tbody></table>
          </div>
        </div>
      </section>

        <section class="card pane" v-if="fix?.rebuild" v-show="tab === 'board'">
          <ConfirmBoard ref="board" :pid="id" :busy="busy" :stamp="meta.updated" @rebuild="runFix('rebuild', true)" @started="load" />
        </section>
        <section class="card pane" v-show="tab === 'issues'">
          <div v-if="fix" class="row srcbar">
            <div class="seg">
              <button :class="{ on: !viewOriginal }" @click="viewOriginal = false">版本 {{ versions[0]?.n }}（最新）：剩 {{ fix.after.total }} 条</button>
              <button :class="{ on: viewOriginal }" @click="viewOriginal = true">原书：{{ audit.issues.total }} 条</button>
            </div>
          </div>
          <p class="muted small">{{ fix && !viewOriginal ? '最新版本里仍存在的问题' : '原书的问题' }}。有意保留的写法可以「忽略」（须写理由），之后生成会跳过它。</p>
          <p v-if="fix?.waivers_changed" class="notice">豁免已更改。下载的文件仍是按旧豁免修复的，重新点「仅规范修复」或「排版重建」后才生效。</p>
          <IssueReport :report="shownIssues" :pid="id" :busy="busy" @changed="load" />
        </section>
        <section class="card pane" v-if="fix" v-show="tab === 'changes'">
          <ChangeLog :changes="fix.changes" :rules="rules" />
          <template v-if="!fix.text.equal">
            <h3>正文文字差异</h3>
            <table><tbody><tr v-for="(c, i) in fix.text.changes" :key="i">
              <td class="mono small">{{ c.file }}</td><td>{{ c.before }}</td><td>→ {{ c.after }}</td></tr></tbody></table>
          </template>
        </section>
        <section class="card pane" v-show="tab === 'epubcheck'">
          <div v-if="fix" class="row srcbar">
            <div class="seg">
              <button :class="{ on: !viewOriginal }" @click="viewOriginal = false">版本 {{ versions[0]?.n }}（最新）：{{ epcCount(fix.epubcheck) }}</button>
              <button :class="{ on: viewOriginal }" @click="viewOriginal = true">原书：{{ epcCount(audit.epubcheck) }}</button>
            </div>
          </div>
          <p class="muted small">{{ fix && !viewOriginal ? '最新版本' : '原书' }}的 EPUBCheck 官方校验结果。</p>
          <EpubcheckList :report="fix && !viewOriginal ? fix.epubcheck : audit.epubcheck" />
        </section>
        <section class="card pane" v-if="fix?.rebuild" v-show="tab === 'rebuild'">
          <p class="muted small">程序识别出的内容类型，以及被删除的内容（书内目录页由导航取代，广告/引流内容、注释区小标题不再需要）。</p>
          <template v-if="fix.rebuild.structures?.length">
            <h3 style="margin-top:0">按模板改写的结构</h3>
            <p class="muted small">A：原书已标明，只做结构转换；B：按规范的识别信号自动改写（04 各节「识别信号」）。</p>
            <table style="width:auto; min-width:240px; margin-bottom:16px">
              <thead><tr><th>结构</th><th>置信</th><th>数量</th></tr></thead>
              <tbody><tr v-for="(r, i) in fix.rebuild.structures" :key="i"><td>{{ r.name }}</td><td class="mono">{{ r.level }}</td><td class="mono">{{ r.count }}</td></tr></tbody>
            </table>
          </template>
          <template v-if="fix.rebuild.suggestions?.length">
            <h3>建议（未自动修改，{{ fix.rebuild.suggestions_total }} 条）</h3>
            <p class="muted small">识别把握不够（C 级）或规范要求用户确认的地方，原样保留。</p>
            <table style="margin-bottom:16px"><tbody>
              <tr v-for="(s, i) in fix.rebuild.suggestions" :key="i"><td style="width:90px"><span class="badge">{{ s.name }}</span></td><td class="small">{{ s.text }}</td></tr>
            </tbody></table>
          </template>
          <div class="row" style="align-items:flex-start; gap:24px">
            <table style="width:auto; min-width:240px">
              <thead><tr><th>内容类型</th><th>数量</th></tr></thead>
              <tbody><tr v-for="r in fix.rebuild.roles" :key="r.role"><td>{{ r.name }}</td><td class="mono">{{ r.count }}</td></tr></tbody>
            </table>
            <div style="flex:1; min-width:300px">
              <h3 style="margin-top:0">删除的内容（{{ fix.rebuild.removed_total }}）</h3>
              <table><tbody>
                <tr v-for="(r, i) in fix.rebuild.removed" :key="i"><td style="width:90px"><span class="badge">{{ r.name }}</span></td><td class="small">{{ r.text || '（空）' }}</td></tr>
              </tbody></table>
              <p v-if="fix.rebuild.removed_total > fix.rebuild.removed.length" class="muted small">仅显示前 {{ fix.rebuild.removed.length }} 条</p>
            </div>
          </div>
        </section>
      </div>

      <aside v-if="previewOpen && versions.length" class="side card">
        <div class="row sidehead">
          <strong>预览</strong><span class="spacer"></span>
          <button class="quiet" title="关闭预览" @click="previewOpen = false">×</button>
        </div>
        <PreviewPanel :pid="id" :versions="versions" :want="previewWant" side />
      </aside>
    </div>
  </template>
</template>

<style scoped>
/* ---- 顶栏：固定在页面顶部，主操作始终可见 ---- */
.bookbar { position: sticky; top: 0; z-index: 10; background: var(--surface); border-bottom: 1px solid var(--border);
  margin: 0 -24px 16px; padding: 10px 24px; }
.bookbar .top { gap: 10px; flex-wrap: nowrap; }
.back { font-size: 20px; text-decoration: none; padding: 0 4px; }
.tt { min-width: 0; }
.tt .row { gap: 8px; flex-wrap: nowrap; }
.title { font-size: 19px; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.info { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gen { gap: 0; flex-wrap: nowrap; }
.gen select { font: inherit; font-size: 14px; padding: 6px 8px; border: 1px solid var(--border); border-right: none;
  border-radius: 6px 0 0 6px; background: var(--surface); height: 36px; }
.gen button { border-radius: 0 6px 6px 0; height: 36px; }
.bookbar button, .bookbar .btn { white-space: nowrap; height: 36px; }
button.on { background: var(--accent-weak); border-color: var(--accent); color: var(--accent); }
.quiet { border-color: transparent; background: transparent; }
.danger.quiet { color: var(--muted); }
.danger.quiet:hover { color: var(--error); border-color: transparent; }
.status { margin: 8px 0 0; }

/* ---- 工作区：左导航 | 主区 | 右侧预览 ---- */
.workspace { display: grid; grid-template-columns: 148px minmax(0, 1fr); gap: 20px; align-items: start; }
.workspace.has-side { grid-template-columns: 148px minmax(0, 1fr) auto; }
.sidenav { position: sticky; top: 84px; display: flex; flex-direction: column; gap: 2px; }
.sidenav button { justify-content: space-between; border-color: transparent; background: transparent; text-align: left; width: 100%; }
.sidenav button:hover { background: var(--surface); border-color: var(--border); }
.sidenav button.active { background: var(--surface); border-color: var(--border); font-weight: 600; }
.sidenav .count { color: var(--muted); font-size: 12px; font-weight: 400; }
.sidenav .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warning); }
.sidenav .sep { margin: 12px 0 2px; padding-left: 14px; color: var(--muted); font-size: 12px; }
.main > .card { margin-bottom: 20px; }
.srcbar { margin-bottom: 4px; }
.seg { display: inline-flex; }
.seg button { border-radius: 0; margin-left: -1px; padding: 3px 12px; font-size: 13px; }
.seg button:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
.seg button:last-child { border-radius: 0 6px 6px 0; }
.seg button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.side { position: sticky; top: 84px; max-height: calc(100vh - 100px); overflow: auto; padding: 12px 16px; margin: 0;
  width: min-content; min-width: 320px; max-width: 60vw; }
.sidehead { margin-bottom: 6px; }
.sidehead button { padding: 2px 10px; font-size: 18px; }

/* ---- 概况（原四步） ---- */
.steps { display: flex; flex-direction: column; gap: 4px; }
.step { display: flex; gap: 14px; padding: 12px 0; border-top: 1px solid var(--border); }
.step:first-child { border-top: none; padding-top: 0; }
.step .num { flex: none; width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
  font-weight: 700; background: var(--info-weak); color: var(--muted); }
.step.done .num { background: var(--ok-weak); color: var(--ok); }
.step.off { opacity: .55; }
.step .body { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.choices { gap: 18px; align-items: center; }
.choices label { display: flex; flex-direction: column; gap: 2px; }
.versions td { padding: 6px 8px; vertical-align: middle; }
.versions tr.latest td { font-weight: 500; }
.versions tr.detail td { border-bottom: none; padding-top: 0; }
.versions .act { text-align: right; white-space: nowrap; }
.versions .act > * + * { margin-left: 10px; }
.bad { color: var(--error); }
.good { color: var(--ok); }
.badge { margin-left: 6px; }

/* ---- 窄屏：单栏，导航横排，预览放到内容上方；版本表各行折成卡片 ---- */
@media (max-width: 1000px) {
  .workspace, .workspace.has-side { grid-template-columns: minmax(0, 1fr); }
  .sidenav { position: static; flex-direction: row; overflow-x: auto; gap: 4px; }
  .sidenav button { width: auto; flex: none; gap: 6px; }
  .sidenav .sep { display: none; }
  .side { position: static; max-height: none; max-width: none; order: -1; }
  .bookbar .top { flex-wrap: wrap; }
  .bookbar { position: static; }
  .tt { flex: 1 1 calc(100% - 44px); order: -1; }
  .back { order: -2; }
}
@media (max-width: 700px) {
  .versions, .versions tbody { display: block; }
  .versions tr { display: flex; flex-wrap: wrap; gap: 2px 10px; padding: 8px 0; border-bottom: 1px solid var(--border); }
  .versions td { border: none; padding: 0; }
  .versions tr.detail td:first-child { display: none; }
  .versions .act { width: 100%; text-align: left; }
}
</style>
