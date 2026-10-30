<script setup>
// 大模型设置（全局）：Claude 原生接口的地址、令牌、分任务模型。令牌只在保存时提交，页面上只显示末 4 位。
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const s = ref(null)
const form = ref({})
const error = ref('')
const notice = ref('')
const testing = ref(false)

async function load() {
  try {
    s.value = await api.llmSettings()
    const { api_key, auth_token, effective_base_url, has_credentials, credential_source, ...rest } = s.value
    form.value = { ...rest, api_key: '', auth_token: '' }
  } catch (e) { error.value = e.message }
}

async function save() {
  error.value = notice.value = ''
  try {
    s.value = await api.saveLlmSettings(form.value)
    form.value.api_key = form.value.auth_token = ''
    notice.value = '已保存'
  } catch (e) { error.value = e.message }
}

async function clearToken(k) {
  s.value = await api.saveLlmSettings({ [k]: null })
}

async function test() {
  testing.value = true
  error.value = notice.value = ''
  try {
    const r = await api.testLlm()
    notice.value = r.ok ? `连接正常：${r.model} @ ${r.base_url}，用时 ${r.seconds} 秒` : '连上了，但回答不对'
  } catch (e) { error.value = e.message } finally { testing.value = false }
}

onMounted(load)
</script>

<template>
  <p><a href="#/">← 返回列表</a></p>
  <section v-if="s" class="card">
    <h1 class="title">大模型设置</h1>
    <p class="muted small">用的是 Claude 原生接口（Anthropic 官方 SDK）。大模型只看书的片段、只给判断，结果在确认板上由你采纳后才生效。
      这里保存的设置存在服务器的 data/settings.json，优先于环境变量 EPUBTS_LLM_*（见仓库里的 .env.example）。</p>
    <p v-if="error" class="notice error">{{ error }}</p>
    <p v-if="notice" class="notice ok">{{ notice }}</p>

    <div class="grid">
      <label>启用</label>
      <div><input v-model="form.enabled" type="checkbox" /> 允许把书的片段发给大模型</div>

      <label>接口地址</label>
      <div><input v-model="form.base_url" placeholder="留空 = 官方 https://api.anthropic.com" />
        <div class="muted small">当前生效：{{ s.effective_base_url }}</div></div>

      <label>API key</label>
      <div><input v-model="form.api_key" type="password" autocomplete="off" :placeholder="s.api_key ? `已保存（${s.api_key}），留空不改` : '官方密钥，走 x-api-key'" />
        <button v-if="s.api_key" class="link" @click="clearToken('api_key')">清除</button></div>

      <label>Bearer 令牌</label>
      <div><input v-model="form.auth_token" type="password" autocomplete="off" :placeholder="s.auth_token ? `已保存（${s.auth_token}），留空不改` : '部分中转要求 Authorization: Bearer，填这里'" />
        <button v-if="s.auth_token" class="link" @click="clearToken('auth_token')">清除</button>
        <div class="muted small">令牌来源：{{ s.credential_source }}</div></div>

      <label>轻量模型</label>
      <div><input v-model="form.model_light" /> 努力程度
        <select v-model="form.effort_light"><option v-for="e in ['low', 'medium', 'high']" :key="e">{{ e }}</option></select>
        <div class="muted small">大批量的简单判断：段落样式、逐条核对结构、图片描述</div></div>

      <label>重型模型</label>
      <div><input v-model="form.model_heavy" /> 努力程度
        <select v-model="form.effort_heavy"><option v-for="e in ['low', 'medium', 'high', 'xhigh']" :key="e">{{ e }}</option></select>
        <div class="muted small">需要通盘考虑的判断：标题层级、注释配对</div></div>

      <label>拒答兜底</label>
      <div><select v-model="form.fallbacks">
          <option value="auto">自动（只在官方接口上开）</option><option value="on">开</option><option value="off">关</option>
        </select>
        <div class="muted small">模型因安全规则拒答时，由服务端改派其他模型接手（中转多半不支持）</div></div>

      <label>并发数</label>
      <div><input v-model.number="form.max_workers" type="number" min="1" max="16" style="width:6em" /></div>
    </div>
    <div class="row" style="margin-top:16px">
      <button class="primary" @click="save">保存</button>
      <button :disabled="testing" @click="test">{{ testing ? '测试中…' : '测试连接' }}</button>
      <span class="muted small">测试会用轻量模型发一句很短的话。</span>
    </div>
  </section>
</template>

<style scoped>
.title { font-size: 22px; margin: 0 0 8px; }
.grid { display: grid; grid-template-columns: 8em 1fr; gap: 12px 16px; align-items: start; margin-top: 12px; }
.grid > label { padding-top: 6px; color: var(--muted); font-size: 14px; }
.grid input:not([type=checkbox]) { width: min(32em, 100%); font: inherit; padding: 4px 6px; }
button.link { border: none; background: none; color: var(--accent); cursor: pointer; }
</style>
