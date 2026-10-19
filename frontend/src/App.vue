<template>
  <router-view v-if="$route.path === '/login'" />

  <div v-else class="app-layout">
    <!-- 桌面端左侧导航 -->
    <aside class="sidebar desktop-only">
      <div class="logo">⚡ 企业协同审批</div>
      <nav class="nav-list">
        <router-link to="/dashboard" class="nav-item">📊 工作台与统计</router-link>
        <router-link to="/applications/new" class="nav-item">✍️ 发起新申请</router-link>
        <router-link to="/applications?mode=MY_APPLICATIONS" class="nav-item">📁 我的申请单</router-link>
        <router-link to="/applications?mode=MY_TODOS" class="nav-item">
          ⏰ 我的待办
          <el-badge v-if="store.todoCount > 0" :value="store.todoCount" class="badge-inline" />
        </router-link>
        <router-link to="/applications?mode=MY_DONE" class="nav-item">✅ 已办事项</router-link>
        <router-link to="/notifications" class="nav-item">
          🔔 通知中心
          <el-badge v-if="store.unreadCount > 0" :value="store.unreadCount" class="badge-inline" />
        </router-link>
        <router-link v-if="store.isAdmin" to="/admin" class="nav-item admin-link">⚙️ 系统管理后台</router-link>
      </nav>
    </aside>

    <!-- 主内容区 -->
    <div class="main-area">
      <header class="topbar">
        <div class="topbar-title">{{ store.user?.department_name }} · {{ store.user?.real_name }}</div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <el-button size="small" @click="$router.push('/notifications')">
            通知 ({{ store.unreadCount }})
          </el-button>
          <el-button size="small" type="danger" plain @click="handleLogout">退出</el-button>
        </div>
      </header>

      <main class="content-body">
        <router-view />
      </main>
    </div>

    <!-- 移动端底部触控导航栏 -->
    <nav class="mobile-tabbar mobile-only">
      <div class="tab-item" @click="$router.push('/dashboard')">📊 首页</div>
      <div class="tab-item" @click="$router.push('/applications/new')">➕ 发起</div>
      <div class="tab-item" @click="$router.push('/applications?mode=MY_TODOS')">
        ⏰ 待办({{ store.todoCount }})
      </div>
      <div class="tab-item" @click="$router.push('/applications?mode=MY_APPLICATIONS')">📁 我的</div>
      <div v-if="store.isAdmin" class="tab-item" @click="$router.push('/admin')">⚙️ 管理</div>
    </nav>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from './store'

const store = useAppStore()
const router = useRouter()

onMounted(() => {
  if (store.isLoggedIn) {
    store.connectSSE(router)
    store.refreshBadgeCounts()
  }
})

function handleLogout() {
  store.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
}
.sidebar {
  width: 220px;
  background: #0f172a;
  color: #f8fafc;
  flex-shrink: 0;
}
.logo {
  padding: 20px;
  font-size: 18px;
  font-weight: 700;
  border-bottom: 1px solid #1e293b;
}
.nav-list {
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 6px;
}
.nav-item {
  color: #cbd5e1;
  text-decoration: none;
  padding: 11px 14px;
  border-radius: 8px;
  font-size: 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.nav-item:hover, .nav-item.router-link-active {
  background: #1e40af;
  color: #fff;
}
.admin-link {
  margin-top: 12px;
  border: 1px dashed #475569;
}
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  background: #fff;
  height: 56px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e2e8f0;
}
.topbar-title {
  font-weight: 600;
  font-size: 14px;
}
.content-body {
  padding: 20px;
  padding-bottom: 80px;
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
}
.mobile-tabbar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 56px;
  background: #ffffff;
  border-top: 1px solid #cbd5e1;
  display: flex !important;
  justify-content: space-around;
  align-items: center;
  z-index: 999;
}
.tab-item {
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  padding: 8px;
}
</style>