<script setup>
// 独立阅读器：直接打开任意一本 EPUB 看——不建项目、不体检、不修改。打开过的书留在列表里，下次直接点开。
import { ref, onMounted } from 'vue'
import { api } from '../api.js'
import PreviewPanel from '../components/PreviewPanel.vue'

const props = defineProps({ rid: { type: String, default: '' } })

const books = ref([])
const error = ref('')
const opening = ref(false)
const dragging = ref(false)

async function load() {
  try { books.value = await api.readerBooks(); error.value = '' } catch (e) { error.value = `加载失败：${e.message}` }
}

async function openFiles(files) {
  const f = [...files].find((x) => x.name.toLowerCase().endsWith('.epub'))
  if (!f) { error.value = '请选择 .epub 文件'; return }
  opening.value = true
  try {
    const m = await api.readerOpen(f)
    location.hash = `#/read/${m.id}`
    await load()
  } catch (e) { error.value = `打开失败：${e.message}` }
  opening.value = false
}

async function remove(b) {
  if (!confirm(`从阅读器里移除《${b.filename}》？（只删阅读器里的这份副本，不影响你电脑上的文件和「我的书」）`)) return
  try {
    await api.readerRemove(b.id)
    if (props.rid === b.id) location.hash = '#/read'
    await load()
  } catch (e) { error.value = `移除失败：${e.message}` }
}

function onDrop(e) { dragging.value = false; openFiles(e.dataTransfer.files) }
const size = (n) => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`
const current = () => books.value.find((b) => b.id === props.rid)

onMounted(load)
</script>

<template>
  <div class="reader">
    <aside class="card shelf" :class="{ dragging }"
           @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
      <h2>阅读器</h2>
      <p class="muted small">直接打开一本 EPUB 来看，不做任何处理。拖入文件，或</p>
      <label class="btn primary"><input type="file" accept=".epub" hidden :disabled="opening"
             @change="openFiles($event.target.files)" />打开 EPUB</label>
      <p v-if="opening" class="row small"><span class="spinner"></span>正在打开…</p>
      <p v-if="error" class="notice error small">{{ error }}</p>
      <ul class="list">
        <li v-for="b in books" :key="b.id" :class="{ on: b.id === rid }">
          <a :href="`#/read/${b.id}`" :title="b.filename">{{ b.filename }}</a>
          <span class="muted small mono">{{ size(b.size) }}</span>
          <button class="link danger" title="从阅读器移除" @click="remove(b)">×</button>
        </li>
      </ul>
      <p v-if="!books.length" class="muted small">还没有打开过书。</p>
    </aside>
    <section class="card view">
      <template v-if="rid">
        <h2 class="title">{{ current()?.filename || '' }}</h2>
        <PreviewPanel :key="rid" :rid="rid" />
      </template>
      <p v-else class="muted">从左边打开一本 EPUB，或点列表里打开过的书。</p>
    </section>
  </div>
</template>

<style scoped>
.reader { display: grid; grid-template-columns: 260px 1fr; gap: 16px; align-items: start; }
@media (max-width: 800px) { .reader { grid-template-columns: 1fr; } }
.shelf.dragging { border-color: var(--accent); background: var(--accent-weak); }
.shelf h2, .view .title { margin-top: 0; }
.view .title { font-size: 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.list { list-style: none; padding: 0; margin: 12px 0 0; }
.list li { display: flex; align-items: center; gap: 6px; padding: 5px 6px; border-radius: 6px; }
.list li.on { background: var(--accent-weak); }
.list li a { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
button.link { border: none; background: none; padding: 0 4px; font-size: 15px; cursor: pointer; }
</style>
