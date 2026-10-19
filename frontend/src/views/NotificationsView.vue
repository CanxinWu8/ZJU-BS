<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 16px;">
      <div>
        <h3 style="margin: 0; display: inline-block; margin-right: 12px;">🔔 站内通知中心</h3>
        <el-checkbox v-model="unreadOnly" @change="loadList">仅看未读 ({{ unreadCount }})</el-checkbox>
      </div>
      <el-button size="small" type="primary" plain @click="readAll">全部标记已读</el-button>
    </div>

    <el-empty v-if="items.length === 0" description="暂无通知记录" />

    <div v-for="n in items" :key="n.id" class="notif-item" :class="{ unread: !n.is_read }" @click="handleClick(n)">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
          <el-tag v-if="!n.is_read" type="danger" size="small" effect="dark" style="margin-right: 6px;">未读</el-tag>
          <el-tag :type="tagType(n.notify_type)" size="small" style="margin-right: 8px;">{{ n.notify_type }}</el-tag>
          <strong style="font-size: 15px;">{{ n.title }}</strong>
        </div>
        <span style="font-size: 12px; color: #94a3b8;">{{ formatTime(n.created_at) }}</span>
      </div>
      <div style="margin-top: 8px; color: #475569; font-size: 14px;">{{ n.content }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'
import { useAppStore } from '../store'

const router = useRouter()
const store = useAppStore()
const unreadOnly = ref(false)
const unreadCount = ref(0)
const items = ref([])

async function loadList() {
  const res = await api.get(`/notifications?unread_only=${unreadOnly.value}`)
  items.value = res.items
  unreadCount.value = res.unread_count
  store.unreadCount = res.unread_count
}

async function handleClick(n) {
  if (!n.is_read) {
    await api.put(`/notifications/${n.id}/read`)
    n.is_read = true
    store.unreadCount = Math.max(0, store.unreadCount - 1)
  }
  if (n.application_id) {
    router.push(`/applications/${n.application_id}`)
  }
}

async function readAll() {
  const res = await api.put('/notifications/read-all')
  ElMessage.success(res.message)
  loadList()
}

function tagType(t) {
  if (t === 'APPROVED') return 'success'
  if (t === 'REJECTED') return 'danger'
  if (t === 'URGE_REMINDER') return 'warning'
  return 'primary'
}

function formatTime(t) {
  return t ? t.replace('T', ' ').slice(0, 19) : ''
}

onMounted(loadList)
</script>

<style scoped>
.notif-item {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.notif-item.unread {
  background: #eff6ff;
  border-color: #bfdbfe;
}
.notif-item:hover {
  background: #f8fafc;
}
</style>