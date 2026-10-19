self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : { title: '企业审批提醒', body: '您有新的审批进度变化' }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      data: { url: data.url || '/' }
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(clients.openWindow(targetUrl))
})