<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api, BUSY, UPLOAD_EXTS } from '../api.js'
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
  const list = [...files].filter((f) => UPLOAD_EXTS.some((x) => f.name.toLowerCase().endsWith(x)))
  if (!list.length) { error.value = '请选择 EPUB、TXT，或 Kindle 的 MOBI、AZW、AZW3 文件'; return }
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

// ---- 删除：单本或多选（正在处理的书不能删，后端也会拒绝） ----
const selected = ref(new Set())
const deleting = ref(false)
const busy = (b) => BUSY.has(b.status)
const deletable = computed(() => books.value.filter((b) => !busy(b)))
const picked = computed(() => books.value.filter((b) => selected.value.has(b.id)))
const allPicked = computed(() => deletable.value.length > 0 && deletable.value.every((b) => selected.value.has(b.id)))
const totalSize = computed(() => books.value.reduce((n, b) => n + (b.size || 0), 0))
const pickedSize = computed(() => picked.value.reduce((n, b) => n + (b.size || 0), 0))
const bookName = (b) => b.title || b.filename || b.id
function toggle(b, on) {
  const s = new Set(selected.value)
  if (on) s.add(b.id); else s.delete(b.id)
  selected.value = s
}
function toggleAll(on) { selected.value = new Set(on ? deletable.value.map((b) => b.id) : []) }
async function removeBooks(list) {
  list = list.filter((b) => !busy(b))
  if (!list.length || deleting.value) return
  const names = list.slice(0, 10).map((b) => `《${bookName(b)}》`).join('\n')
  const more = list.length > 10 ? `\n……等共 ${list.length} 本` : ''
  if (!confirm(`删除${list.length === 1 ? '这本书' : `下面 ${list.length} 本书`}的原件和所有处理结果？删除后无法恢复。\n\n${names}${more}`)) return
  deleting.value = true
  const failed = []
  for (const b of list) {
    try { await api.remove(b.id) } catch (e) { failed.push(`《${bookName(b)}》：${e.message}`) }
  }
  deleting.value = false
  const s = new Set(selected.value)
  for (const b of list) s.delete(b.id)
  selected.value = s
  await load()
  if (failed.length) error.value = `有 ${failed.length} 本没删掉：${failed.join('；')}`
}

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <section class="card drop" :class="{ dragging }"
           @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
    <h2>上传电子书</h2>
    <p class="muted">拖入文件，或
      <label class="btn primary"><input type="file" :accept="UPLOAD_EXTS.join(',')" multiple hidden
             @change="upload($event.target.files)" :disabled="uploading" />选择文件</label>
    </p>
    <p class="muted small">支持 EPUB、TXT，以及 Kindle 的 MOBI、AZW、AZW3（先转成 EPUB；TXT 按「第X章」等写法识别章节，有 DRM 加密的书无法转换）。上传后会自动体检。原件不会被修改，修复结果另存一份。</p>
    <p v-if="uploading" class="row"><span class="spinner"></span>上传中…</p>
    <p v-if="error" class="notice error">{{ error }}</p>
  </section>

  <section class="card">
    <div class="row list-head">
      <h2>我的书</h2>
      <span v-if="books.length" class="muted small">共 {{ books.length }} 本 · {{ size(totalSize) }}</span>
      <span class="spacer"></span>
      <template v-if="picked.length">
        <span class="small">已选 {{ picked.length }} 本（{{ size(pickedSize) }}）</span>
        <button class="danger" :disabled="deleting" @click="removeBooks(picked)">
          <span v-if="deleting" class="spinner"></span>删除所选</button>
        <button :disabled="deleting" @click="toggleAll(false)">取消选择</button>
      </template>
    </div>
    <p v-if="!books.length" class="muted">还没有上传过书。</p>
    <table v-else>
      <thead><tr>
        <th class="chk"><input type="checkbox" title="全选（正在处理的书除外）" :checked="allPicked"
                               :disabled="!deletable.length || deleting" @change="toggleAll($event.target.checked)" /></th>
        <th>书名</th><th>文件</th><th>版本</th><th>大小</th><th>上传时间</th><th>状态</th><th></th></tr></thead>
      <tbody>
        <tr v-for="b in books" :key="b.id" class="clickable" :class="{ picked: selected.has(b.id) }" @click="open(b.id)">
          <td class="chk" @click.stop>
            <input type="checkbox" :checked="selected.has(b.id)" :disabled="busy(b) || deleting"
                   :title="busy(b) ? '正在处理中，不能删除' : '选中'" @change="toggle(b, $event.target.checked)" /></td>
          <td><a :href="`#/book/${b.id}`">{{ b.title || '（未读到书名）' }}</a><div class="muted small">{{ b.author }}</div></td>
          <td class="small muted">{{ b.filename }}</td>
          <td class="mono">{{ b.version || '—' }}<div v-if="b.source_format" class="muted small" :title="`由 ${b.source_format.toUpperCase()} 转换`">{{ b.source_format.toUpperCase() }}</div></td>
          <td class="mono">{{ size(b.size) }}</td>
          <td class="small">{{ when(b.created) }}</td>
          <td><StatusBadge :status="b.status" /></td>
          <td class="ops" @click.stop>
            <button class="link danger" :disabled="busy(b) || deleting"
                    :title="busy(b) ? '正在处理中，不能删除' : '删除这本书'" @click="removeBooks([b])">删除</button></td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.drop { border-style: dashed; text-align: center; }
.drop.dragging { border-color: var(--accent); background: var(--accent-weak); }
.list-head { margin-bottom: 12px; }
.list-head h2 { margin: 0; }
.chk { width: 1%; padding-right: 0; }
.ops { width: 1%; text-align: right; white-space: nowrap; }
tr.picked td { background: var(--accent-weak); }
button.link { border: none; background: none; padding: 0 4px; font-size: 13px; cursor: pointer; }
button.link:disabled { opacity: .4; }
</style>
