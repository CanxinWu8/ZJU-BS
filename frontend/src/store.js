import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElNotification } from 'element-plus'
import api from './api'

export const useAppStore = defineStore('app', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('user_info') || 'null'))
  const unreadCount = ref(0)
  const todoCount = ref(0)
  let sseSource = null

  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.roles?.includes('ADMIN'))

  function setAuth(newToken, userInfo) {
    token.value = newToken
    user.value = userInfo
    localStorage.setItem('access_token', newToken)
    localStorage.setItem('user_info', JSON.stringify(userInfo))
    connectSSE()
    registerBrowserPush()
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('user_info')
    if (sseSource) {
      sseSource.close()
      sseSource = null
    }
  }

  async function refreshBadgeCounts() {
    if (!token.value) return
    try {
      const res = await api.get('/stats/overview?scope=PERSONAL')
      todoCount.value = res.personal_todo_summary.my_pending_todo_count
      unreadCount.value = res.personal_todo_summary.my_unread_notify_count
    } catch (_) {}
  }

  function connectSSE(router) {
    if (!token.value) return
    if (sseSource) sseSource.close()

    sseSource = new EventSource(`/api/v1/notifications/stream?token=${token.value}`)
    sseSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'INIT_SYNC') {
          unreadCount.value = data.unread_count
          todoCount.value = data.todo_count
        } else if (data.type === 'NEW_NOTIFICATION') {
          unreadCount.value = data.unread_count
          todoCount.value = data.todo_count
          const n = data.notification

          // 1. 页面打开时自动显示实时提醒，点击直接进入申请详情
          ElNotification({
            title: n.title,
            message: `${n.content}（点击查看详情）`,
            type: n.notify_type === 'REJECTED' ? 'error' : n.notify_type === 'APPROVED' ? 'success' : 'warning',
            duration: 7000,
            onClick: () => {
              if (n.application_id) {
                window.location.hash = `#/applications/${n.application_id}`
              } else {
                window.location.hash = '#/notifications'
              }
            }
          })

          // 2. 页面处于后台或最小化时，触发系统级 Notification 通知栏提醒
          if ('Notification' in window && Notification.permission === 'granted') {
            const sysNotify = new Notification(n.title, {
              body: n.content,
              tag: `notif_${n.id}`
            })
            sysNotify.onclick = () => {
              window.focus()
              if (n.application_id) {
                window.location.hash = `#/applications/${n.application_id}`
              }
            }
          }
        }
      } catch (_) {}
    }
  }

  async function registerBrowserPush() {
    try {
      if ('Notification' in window && Notification.permission === 'default') {
        await Notification.requestPermission()
      }
      if ('serviceWorker' in navigator) {
        const reg = await navigator.serviceWorker.register('/sw.js')
        await api.post('/notifications/webpush-subscribe', {
          subscription: {
            endpoint: reg.scope,
            permission: Notification.permission,
            userAgent: navigator.userAgent,
            subscribedAt: new Date().toISOString()
          }
        })
      }
    } catch (_) {
      // 拒绝权限或不支持时静默降级，站内通知依然100%可用
    }
  }

  return {
    token,
    user,
    unreadCount,
    todoCount,
    isLoggedIn,
    isAdmin,
    setAuth,
    logout,
    refreshBadgeCounts,
    connectSSE,
    registerBrowserPush
  }
})