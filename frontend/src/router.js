import { createRouter, createWebHashHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import DashboardView from './views/DashboardView.vue'
import ApplicationListView from './views/ApplicationListView.vue'
import ApplicationFormView from './views/ApplicationFormView.vue'
import ApplicationDetailView from './views/ApplicationDetailView.vue'
import NotificationsView from './views/NotificationsView.vue'
import AdminView from './views/AdminView.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: LoginView, meta: { public: true } },
  { path: '/dashboard', component: DashboardView },
  { path: '/applications', component: ApplicationListView },
  { path: '/applications/new', component: ApplicationFormView },
  { path: '/applications/:id/edit', component: ApplicationFormView },
  { path: '/applications/:id', component: ApplicationDetailView },
  { path: '/notifications', component: NotificationsView },
  { path: '/admin', component: AdminView }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('access_token')
  if (!to.meta.public && !token) {
    return next('/login')
  }
  next()
})

export default router