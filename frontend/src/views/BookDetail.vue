<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api, BUSY } from '../api.js'
import StatusBadge from '../components/StatusBadge.vue'
import StatTile from '../components/StatTile.vue'
import IssueReport from '../components/IssueReport.vue'
import EpubcheckList from '../components/EpubcheckList.vue'
import ChangeLog from '../components/ChangeLog.vue'

const props = defineProps({ id: String })
const data = ref(null)
const rules = ref({})
const error = ref('')
const tab = ref('issues')
let timer

const meta = computed(() => data.value?.meta)
const audit = computed(() => data.value?.audit)
const fix = computed(() => data.value?.fix)
const busy = computed(() => meta.value && BUSY.has(meta.value.status))
const autoCount = computed(() => audit.value?.issues.summary?.auto_fixable ?? 0)

async function load() {
  try {
    data.value = await api.book(props.id)
    error.value = ''
  } catch (e) { error.value = e.message }
  clearTimeout(timer)
  if (busy.value) timer = setTimeout(load, 1500)
}

async function runFix(mode) {
  try {
    await api.fix(props.id, mode)
    tab.value = mode === 'rebuild' ? 'rebuild' : 'changes'
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
        {{ meta.status === 'fixing' ? '正在修复并重新校验，较大的书需要几十秒…' : '正在体检（含 epubcheck 校验）…' }}</p>
      <p v-if="meta.status === 'error'" class="notice error">{{ meta.message }}</p>
    </section>

    <template v-if="audit">
      <section class="card">
        <div class="row">
          <h2 style="margin:0">体检结果</h2>
          <span class="spacer"></span>
          <button :disabled="busy" @click="runFix('basic')"
                  title="只修规范错误与伪排版，不改变版面">仅规范修复</button>
          <button class="primary" :disabled="busy" @click="runFix('rebuild')"
                  title="识别标题、插图、注释等并重建为规范的 EPUB 3，套用统一排版主题">排版重建（推荐）</button>
        </div>
        <div class="row tiles">
          <StatTile label="epubcheck 错误" :value="audit.epubcheck.available ? audit.epubcheck.blocking : '—'"
                    :tone="audit.epubcheck.blocking ? 'error' : 'ok'" sub="规范硬错误（含致命）" />
          <StatTile label="本工具发现的问题" :value="audit.issues.total"
                    :sub="`错误 ${sevCount(audit.issues, 'error')} · 警告 ${sevCount(audit.issues, 'warning')}`" />
          <StatTile label="可自动修复" :value="autoCount" sub="确定性修复，不改动正文文字" />
        </div>
      </section>

      <section v-if="fix && !busy" class="card">
        <div class="row">
          <h2 style="margin:0">{{ fix.mode === 'rebuild' ? '排版重建结果' : '规范修复结果' }}</h2>
          <span class="spacer"></span>
          <a class="btn" :href="api.downloadUrl(id, 'original')">下载原件</a>
          <a class="btn primary" :href="api.downloadUrl(id, 'fixed')">下载优化后的 EPUB</a>
        </div>
        <div class="row tiles">
          <StatTile label="epubcheck 错误" :value="`${audit.epubcheck.blocking ?? '—'} → ${fix.epubcheck.blocking ?? '—'}`"
                    :tone="fix.epubcheck.blocking ? 'error' : 'ok'" />
          <StatTile label="本工具发现的问题" :value="`${fix.before.total} → ${fix.after.total}`"
                    :sub="fix.after.total ? '剩余的需确认、大模型或人工处理' : ''" />
          <StatTile label="正文文字" :value="fix.text.equal ? '完整' : '有差异'" :tone="fix.text.equal ? 'ok' : 'error'"
                    :sub="fix.text.summary" />
          <StatTile v-if="fix.rebuild" label="重建" :value="`${fix.rebuild.files} 个文件`"
                    :sub="`注释 ${fix.rebuild.notes} 条 · 删除 ${fix.rebuild.removed_total} 块${fix.rebuild.vertical ? ' · 竖排' : ''}`" />
          <StatTile v-else label="修改" :value="fix.changes.length" :sub="`输出 ${kb(fix.size)}`" />
        </div>
      </section>

      <section class="card">
        <div class="tabs row">
          <button :class="{ active: tab === 'issues' }" @click="tab = 'issues'">
            问题清单（{{ fix ? fix.after.total : audit.issues.total }}）</button>
          <button :class="{ active: tab === 'epubcheck' }" @click="tab = 'epubcheck'">epubcheck</button>
          <button v-if="fix?.rebuild" :class="{ active: tab === 'rebuild' }" @click="tab = 'rebuild'">重建详情</button>
          <button v-if="fix" :class="{ active: tab === 'changes' }" @click="tab = 'changes'">修改记录（{{ fix.changes.length }}）</button>
        </div>
        <div v-show="tab === 'issues'">
          <p class="muted small">{{ fix ? '修复后仍存在的问题' : '修复前的问题' }}，按文件分组。有意保留的写法可以「忽略」（须写理由），之后修复会跳过它。</p>
          <p v-if="fix?.waivers_changed" class="notice">豁免已更改。下载的文件仍是按旧豁免修复的，重新点「仅规范修复」或「排版重建」后才生效。</p>
          <IssueReport :report="fix ? fix.after : audit.issues" :pid="id" :busy="busy" @changed="load" />
        </div>
        <div v-show="tab === 'epubcheck'">
          <p class="muted small">{{ fix ? '修复后' : '修复前' }}的 EPUBCheck 官方校验结果。</p>
          <EpubcheckList :report="fix ? fix.epubcheck : audit.epubcheck" />
        </div>
        <div v-if="fix?.rebuild" v-show="tab === 'rebuild'">
          <p class="muted small">程序识别出的内容类型，以及被删除的内容（书内目录页由导航取代，广告/引流内容、注释区小标题不再需要）。</p>
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
.tabs { gap: 4px; border-bottom: 1px solid var(--border); margin: -4px 0 12px; padding-bottom: 8px; }
.tabs button { border-color: transparent; }
.tabs button.active { border-color: var(--border); background: var(--bg); font-weight: 600; }
</style>
