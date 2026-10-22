<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api, BUSY } from '../api.js'
import StatusBadge from '../components/StatusBadge.vue'

const books = ref([])
const error = ref('')
const uploading = ref(false)
const dragging = ref(false)
let timer

async function load() {
  try {
    books.value = await api.books()
    error.value = ''
  } catch (e) { error.value = `加载失败：${e.message}` }
  clearTimeout(timer)
  if (books.value.some((b) => BUSY.has(b.status))) timer = setTimeout(load, 1500)
}

async function upload(files) {
  const list = [...files].filter((f) => f.name.toLowerCase().endsWith('.epub'))
  if (!list.length) { error.value = '请选择 .epub 文件'; return }
  uploading.value = true
  try {
    let last
    for (const f of list) last = await api.upload(f)
    if (list.length === 1) location.hash = `#/book/${last.id}`
    else await load()
  } catch (e) { error.value = `上传失败：${e.message}` }
  uploading.value = false
}

function onDrop(e) { dragging.value = false; upload(e.dataTransfer.files) }
const open = (id) => { location.hash = `#/book/${id}` }
const size = (n) => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`
const when = (t) => new Date(t * 1000).toLocaleString('zh-CN', { hour12: false })

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <section class="card drop" :class="{ dragging }"
           @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
    <h2>上传 EPUB</h2>
    <p class="muted">拖入文件，或
      <label class="btn primary"><input type="file" accept=".epub" multiple hidden
             @change="upload($event.target.files)" :disabled="uploading" />选择文件</label>
    </p>
    <p class="muted small">上传后会自动体检。原件不会被修改，修复结果另存一份。</p>
    <p v-if="uploading" class="row"><span class="spinner"></span>上传中…</p>
    <p v-if="error" class="notice error">{{ error }}</p>
  </section>

  <section class="card">
    <h2>我的书</h2>
    <p v-if="!books.length" class="muted">还没有上传过书。</p>
    <table v-else>
      <thead><tr><th>书名</th><th>文件</th><th>版本</th><th>大小</th><th>上传时间</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="b in books" :key="b.id" class="clickable" @click="open(b.id)">
          <td><a :href="`#/book/${b.id}`">{{ b.title || '（未读到书名）' }}</a><div class="muted small">{{ b.author }}</div></td>
          <td class="small muted">{{ b.filename }}</td>
          <td class="mono">{{ b.version || '—' }}</td>
          <td class="mono">{{ size(b.size) }}</td>
          <td class="small">{{ when(b.created) }}</td>
          <td><StatusBadge :status="b.status" /></td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.drop { border-style: dashed; text-align: center; }
.drop.dragging { border-color: var(--accent); background: var(--accent-weak); }
</style>
