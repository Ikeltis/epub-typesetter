<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import BookList from './views/BookList.vue'
import BookDetail from './views/BookDetail.vue'

// 极简 hash 路由：#/ 列表，#/book/<id> 详情
const hash = ref(location.hash)
const onHash = () => { hash.value = location.hash }
onMounted(() => window.addEventListener('hashchange', onHash))
onUnmounted(() => window.removeEventListener('hashchange', onHash))
const bookId = computed(() => (hash.value.match(/^#\/book\/([0-9a-f]{12})$/) || [])[1])
</script>

<template>
  <header class="topbar">
    <a href="#/" class="brand">EPUB 排版优化</a>
    <span class="tagline">把已有的 EPUB 修成规范、好读的 EPUB 3</span>
  </header>
  <main class="container">
    <BookDetail v-if="bookId" :id="bookId" :key="bookId" />
    <BookList v-else />
  </main>
</template>
