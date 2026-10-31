<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api, BUSY } from '../api.js'
import StatusBadge from '../components/StatusBadge.vue'
import IssueReport from '../components/IssueReport.vue'
import EpubcheckList from '../components/EpubcheckList.vue'
import ChangeLog from '../components/ChangeLog.vue'
import ConfirmBoard from '../components/ConfirmBoard.vue'

const props = defineProps({ id: String, initialTab: { type: String, default: '' } })
const data = ref(null)
const rules = ref({})
const error = ref('')
const tab = ref(props.initialTab || 'issues')
// 当前标签页写进地址，刷新后停在原处
watch(tab, (t) => { history.replaceState(null, '', `#/book/${props.id}${t === 'issues' ? '' : '/' + t}`) })
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
const details = ref(null)
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
function openTab(t) {
  tab.value = t
  viewOriginal.value = false
  details.value?.scrollIntoView({ behavior: 'smooth' })
}
function showOriginal() {
  viewOriginal.value = true
  tab.value = 'issues'
  details.value?.scrollIntoView({ behavior: 'smooth' })
}

async function load() {
  try {
    data.value = await api.book(props.id)
    error.value = ''
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
  <p><a href="#/">← 返回列表</a></p>
  <p v-if="error" class="notice error">{{ error }}</p>
  <template v-if="meta">
    <section class="card">
      <div class="row">
        <h1 class="title">{{ meta.title || meta.filename }}</h1>
        <StatusBadge :status="meta.status" />
        <span class="spacer"></span>
        <button class="danger" :disabled="busy" @click="remove">删除</button>
      </div>
      <p class="muted small">
        {{ meta.author || '作者未知' }} · {{ meta.filename }} · EPUB {{ meta.version || '?' }}
        <template v-if="audit"> · {{ audit.book.documents }} 个正文文件 · {{ kb(meta.size) }}</template>
      </p>
      <p v-if="busy" class="row"><span class="spinner"></span>
        {{ meta.status === 'fixing' ? '正在修复并重新校验，较大的书需要几十秒…'
          : meta.status === 'thinking' ? (meta.message || '大模型分析中…') : '正在体检（含 epubcheck 校验）…' }}</p>
      <p v-if="meta.status === 'error'" class="notice error">{{ meta.message }}</p>
      <p v-else-if="!busy && meta.message" class="notice">{{ meta.message }}</p>
    </section>

    <template v-if="audit">
      <section class="card steps">
        <!-- ① 体检 -->
        <div class="step done">
          <div class="num">1</div>
          <div class="body">
            <div class="row"><strong>体检</strong><span class="muted small">原书的问题</span></div>
            <div class="small">
              epubcheck <b :class="{ bad: audit.epubcheck.blocking }">{{ audit.epubcheck.available ? audit.epubcheck.blocking : '—' }}</b> 个错误 ·
              本工具发现 <b>{{ audit.issues.total }}</b> 处问题（错误 {{ sevCount(audit.issues, 'error') }}、警告 {{ sevCount(audit.issues, 'warning') }}），其中 {{ autoCount }} 处可自动修
              <a href="#" @click.prevent="showOriginal()">查看</a>
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
                    <a class="btn" :class="{ primary: i === 0 }" :href="api.downloadUrl(id, 'v' + v.n)">下载</a></td>
                </tr>
                <tr v-if="open[v.n]" class="detail"><td></td><td colspan="4" class="small muted">
                  {{ v.mode === 'rebuild' ? `重建为 ${v.files} 个文件，注释 ${v.notes} 条；` : '' }}剩余问题 {{ v.issues }} 处；{{ v.text }}；{{ kb(v.size) }}
                  <template v-if="v.mode === 'rebuild'">；用了 {{ v.decisions }} 处确认板上的决定<template v-if="v.llm">，其中 {{ v.llm }} 处与大模型意见一致</template></template>
                </td></tr>
              </template>
              <tr>
                <td class="mono">原件</td><td class="muted">上传的原书，未改动</td><td></td><td></td>
                <td class="act"><a class="btn" :href="api.downloadUrl(id, 'original')">下载</a></td>
              </tr>
            </tbody></table>
          </div>
        </div>
      </section>

      <section class="card" ref="details">
        <div class="row" style="margin-bottom:8px">
          <h2 style="margin:0; font-size:17px">详细信息</h2>
          <span class="muted small">{{ fix && !viewOriginal ? `最新版本（版本 ${versions[0]?.n ?? ''}）` : '原书' }}</span>
          <a v-if="fix" href="#" class="small" @click.prevent="viewOriginal = !viewOriginal">{{ viewOriginal ? '看最新版本' : '看原书' }}</a>
        </div>
        <div class="tabs row">
          <button :class="{ active: tab === 'issues' }" @click="tab = 'issues'">
            问题清单（{{ shownIssues.total }}）</button>
          <button :class="{ active: tab === 'epubcheck' }" @click="tab = 'epubcheck'">epubcheck</button>
          <button v-if="fix?.rebuild" :class="{ active: tab === 'board' }" @click="tab = 'board'">确认板</button>
          <button v-if="fix?.rebuild" :class="{ active: tab === 'rebuild' }" @click="tab = 'rebuild'">重建详情</button>
          <button v-if="fix" :class="{ active: tab === 'changes' }" @click="tab = 'changes'">修改记录（{{ fix.changes.length }}）</button>
        </div>
        <div v-show="tab === 'issues'">
          <p class="muted small">{{ fix && !viewOriginal ? '最新版本里仍存在的问题' : '原书的问题' }}，按文件分组。有意保留的写法可以「忽略」（须写理由），之后生成会跳过它。</p>
          <p v-if="fix?.waivers_changed" class="notice">豁免已更改。下载的文件仍是按旧豁免修复的，重新点「仅规范修复」或「排版重建」后才生效。</p>
          <IssueReport :report="shownIssues" :pid="id" :busy="busy" @changed="load" />
        </div>
        <div v-show="tab === 'epubcheck'">
          <p class="muted small">{{ fix && !viewOriginal ? '最新版本' : '原书' }}的 EPUBCheck 官方校验结果。</p>
          <EpubcheckList :report="fix && !viewOriginal ? fix.epubcheck : audit.epubcheck" />
        </div>
        <div v-if="fix?.rebuild" v-show="tab === 'board'">
          <ConfirmBoard :pid="id" :busy="busy" :stamp="meta.updated" @rebuild="runFix('rebuild', true)" @started="load" />
        </div>
        <div v-if="fix?.rebuild" v-show="tab === 'rebuild'">
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
        </div>
        <div v-if="fix" v-show="tab === 'changes'">
          <ChangeLog :changes="fix.changes" :rules="rules" />
          <template v-if="!fix.text.equal">
            <h3>正文文字差异</h3>
            <table><tbody><tr v-for="(c, i) in fix.text.changes" :key="i">
              <td class="mono small">{{ c.file }}</td><td>{{ c.before }}</td><td>→ {{ c.after }}</td></tr></tbody></table>
          </template>
        </div>
      </section>
    </template>
  </template>
</template>

<style scoped>
.title { font-size: 22px; margin: 0; }
.tiles { margin-top: 14px; align-items: stretch; }
.steps { display: flex; flex-direction: column; gap: 4px; }
.step { display: flex; gap: 14px; padding: 12px 0; border-top: 1px solid var(--border); }
.step:first-child { border-top: none; padding-top: 0; }
.step .num { flex: none; width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
  font-weight: 700; background: var(--info-weak); color: var(--muted); }
.step.done .num { background: var(--ok-weak); color: var(--ok); }
.step.off { opacity: .55; }
.step .body { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.choices { gap: 18px; align-items: center; }
.choices label { display: flex; flex-direction: column; gap: 2px; }
.versions td { padding: 6px 8px; vertical-align: middle; }
.versions tr.latest td { font-weight: 500; }
.versions tr.detail td { border-bottom: none; padding-top: 0; }
.versions .act { text-align: right; white-space: nowrap; display: flex; gap: 10px; align-items: center; justify-content: flex-end; }
.bad { color: var(--error); }
.good { color: var(--ok); }
.badge { margin-left: 6px; }
.tabs { gap: 4px; border-bottom: 1px solid var(--border); margin: -4px 0 12px; padding-bottom: 8px; }
.tabs button { border-color: transparent; }
.tabs button.active { border-color: var(--border); background: var(--bg); font-weight: 600; }
</style>
