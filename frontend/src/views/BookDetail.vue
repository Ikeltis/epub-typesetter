<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api, BUSY } from '../api.js'
import StatusBadge from '../components/StatusBadge.vue'
import StatTile from '../components/StatTile.vue'
import IssueGroups from '../components/IssueGroups.vue'
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
const autoCount = computed(() => (audit.value?.issues.items || []).filter((i) => i.fix_level === 'auto').length)

async function load() {
  try {
    data.value = await api.book(props.id)
    error.value = ''
  } catch (e) { error.value = e.message }
  clearTimeout(timer)
  if (busy.value) timer = setTimeout(load, 1500)
}

async function runFix() {
  try {
    await api.fix(props.id)
    tab.value = 'changes'
    await load()
  } catch (e) { error.value = e.message }
}

async function remove() {
  if (!confirm('删除这本书的原件和所有处理结果？')) return
  await api.remove(props.id)
  location.hash = '#/'
}

const sevCount = (rep, s) => rep?.by_severity?.[s] || 0
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
          <button v-if="!fix" class="primary" :disabled="busy || !autoCount" @click="runFix">
            应用自动修复（{{ autoCount }} 项）</button>
          <button v-else :disabled="busy" @click="runFix">重新修复</button>
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
          <h2 style="margin:0">修复结果</h2>
          <span class="spacer"></span>
          <a class="btn" :href="api.downloadUrl(id, 'original')">下载原件</a>
          <a class="btn primary" :href="api.downloadUrl(id, 'fixed')">下载优化后的 EPUB</a>
        </div>
        <div class="row tiles">
          <StatTile label="epubcheck 错误" :value="`${audit.epubcheck.blocking ?? '—'} → ${fix.epubcheck.blocking ?? '—'}`"
                    :tone="fix.epubcheck.blocking ? 'error' : 'ok'" />
          <StatTile label="本工具发现的问题" :value="`${fix.before.total} → ${fix.after.total}`"
                    :sub="fix.after.total ? '剩余的需确认、大模型或人工处理' : ''" />
          <StatTile label="正文文字" :value="fix.text.equal ? '一致' : '有差异'" :tone="fix.text.equal ? 'ok' : 'error'"
                    :sub="fix.text.equal ? `共 ${fix.text.length} 字，未增删` : fix.text.summary" />
          <StatTile label="修改" :value="fix.changes.length" :sub="`输出 ${kb(fix.size)}`" />
        </div>
      </section>

      <section class="card">
        <div class="tabs row">
          <button :class="{ active: tab === 'issues' }" @click="tab = 'issues'">
            问题清单（{{ fix ? fix.after.total : audit.issues.total }}）</button>
          <button :class="{ active: tab === 'epubcheck' }" @click="tab = 'epubcheck'">epubcheck</button>
          <button v-if="fix" :class="{ active: tab === 'changes' }" @click="tab = 'changes'">修改记录（{{ fix.changes.length }}）</button>
        </div>
        <div v-show="tab === 'issues'">
          <p class="muted small">{{ fix ? '修复后仍存在的问题' : '修复前的问题' }}，点开可看每个文件的明细。</p>
          <IssueGroups :items="(fix ? fix.after : audit.issues).items" :rules="rules" />
        </div>
        <div v-show="tab === 'epubcheck'">
          <p class="muted small">{{ fix ? '修复后' : '修复前' }}的 EPUBCheck 官方校验结果。</p>
          <EpubcheckList :report="fix ? fix.epubcheck : audit.epubcheck" />
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
