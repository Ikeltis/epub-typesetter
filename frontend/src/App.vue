<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import BookList from './views/BookList.vue'
import BookDetail from './views/BookDetail.vue'
import SettingsView from './views/SettingsView.vue'

// 极简 hash 路由：#/ 列表，#/book/<id>[/<标签页>] 详情
const hash = ref(location.hash)
const onHash = () => { hash.value = location.hash }
onMounted(() => window.addEventListener('hashchange', onHash))
onUnmounted(() => window.removeEventListener('hashchange', onHash))
const route = computed(() => hash.value.match(/^#\/book\/([0-9a-f]{12})(?:\/([a-z]+))?$/) || [])
const bookId = computed(() => route.value[1])
const bookTab = computed(() => route.value[2] || '')
</script>

<template>
  <header class="topbar">
    <a href="#/" class="brand">EPUB 排版优化</a>
    <span class="tagline">把已有的 EPUB 修成规范、好读的 EPUB 3</span>
    <span style="flex:1"></span>
    <a href="#/settings" class="small">大模型设置</a>
  </header>
  <main class="container">
    <SettingsView v-if="hash === '#/settings'" />
    <BookDetail v-else-if="bookId" :id="bookId" :key="bookId" :initial-tab="bookTab" />
    <BookList v-else />
  </main>
</template>
