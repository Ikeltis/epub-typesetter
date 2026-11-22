<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import BookList from './views/BookList.vue'
import BookDetail from './views/BookDetail.vue'
import SettingsView from './views/SettingsView.vue'
import ReaderView from './views/ReaderView.vue'

// 极简 hash 路由：#/ 列表，#/book/<id>[/<标签页>] 详情，#/read[/<id>] 独立阅读器
const hash = ref(location.hash)
const onHash = () => { hash.value = location.hash }
onMounted(() => window.addEventListener('hashchange', onHash))
onUnmounted(() => window.removeEventListener('hashchange', onHash))
const route = computed(() => hash.value.match(/^#\/book\/([0-9a-f]{12})(?:\/([a-z]+))?$/) || [])
const bookId = computed(() => route.value[1])
const bookTab = computed(() => route.value[2] || '')
const readMatch = computed(() => hash.value.match(/^#\/read(?:\/([0-9a-f]{12}))?$/))
</script>

<template>
  <header class="topbar">
    <a href="#/" class="brand" title="缮本：修书，修出一个好本子">缮本</a>
    <span class="tagline">EPUB 排版优化 · 把已有的 EPUB 修成规范、好读的 EPUB 3</span>
    <span style="flex:1"></span>
    <a href="#/read" class="small">阅读器</a>
    <a href="#/settings" class="small">大模型设置</a>
  </header>
  <main class="container" :class="{ wide: (bookId || readMatch) && hash !== '#/settings' }">
    <SettingsView v-if="hash === '#/settings'" />
    <ReaderView v-else-if="readMatch" :rid="readMatch[1] || ''" />
    <BookDetail v-else-if="bookId" :id="bookId" :key="bookId" :initial-tab="bookTab" />
    <BookList v-else />
  </main>
</template>
