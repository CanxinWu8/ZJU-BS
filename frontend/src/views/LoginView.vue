<template>
  <div class="login-wrapper">
    <div class="login-box">
      <div class="brand-header">
        <h2>企业智能协同审批系统</h2>
        <p>采购 · 差旅 · 报销 · 动态自定义流程引擎</p>
      </div>

      <el-tabs v-model="activeTab" stretch>
        <!-- 登录面板 -->
        <el-tab-pane label="账号登录" name="login">
          <el-form :model="loginForm" label-position="top" @submit.prevent="handleLogin">
            <el-form-item label="用户名">
              <el-input v-model="loginForm.username" placeholder="请输入用户名" size="large" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="loginForm.password" type="password" show-password placeholder="请输入密码" size="large" />
            </el-form-item>
            <el-button type="primary" size="large" :loading="loading" style="width: 100%; margin-top: 8px;" @click="handleLogin">
              立即登录
            </el-button>
          </el-form>

          <!-- 课程答辩演示快捷切换面板 -->
          <div class="demo-accounts">
            <div class="demo-title">⚡ 课程演示账号一键切换（密码均为 Zju123456）：</div>
            <div class="demo-grid">
              <el-button size="small" @click="quickLogin('emp_rnd')">员工 1(研发员工)</el-button>
              <el-button size="small" @click="quickLogin('emp_mkt')">员工 2(市场员工)</el-button>
              <el-button size="small" type="primary" plain @click="quickLogin('mgr_rnd')">经理 1(研发经理)</el-button>
              <el-button size="small" type="success" plain @click="quickLogin('fin_auditor')">经理 3(财务经理)</el-button>
              <el-button size="small" type="warning" plain @click="quickLogin('ceo')">总管(企业负责人)</el-button>
              <el-button size="small" type="danger" plain @click="quickLogin('admin')">系统管理员</el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- 注册面板 -->
        <el-tab-pane label="新员工注册" name="register">
          <el-form :model="regForm" label-position="top">
            <el-form-item label="用户名 (唯一)">
              <el-input v-model="regForm.username" placeholder="至少3个字符，如 user_01" />
            </el-form-item>
            <el-form-item label="真实姓名">
              <el-input v-model="regForm.real_name" placeholder="请输入真实姓名" />
            </el-form-item>
            <el-form-item label="企业邮箱 (唯一)">
              <el-input v-model="regForm.email" placeholder="example@zju.edu.cn" />
            </el-form-item>
            <el-form-item label="申请加入部门">
              <el-select v-model="regForm.department_id" placeholder="请选择部门" style="width: 100%;">
                <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="登录密码 (不少于8位，BCrypt加密存储)">
              <el-input v-model="regForm.password" type="password" show-password placeholder="至少8位字符" />
            </el-form-item>
            <el-button type="success" size="large" :loading="loading" style="width: 100%;" @click="handleRegister">
              提交注册 (默认普通员工权限)
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
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
const activeTab = ref('login')
const loading = ref(false)
const departments = ref([])

const loginForm = ref({ username: 'emp_rnd', password: 'Zju123456' })
const regForm = ref({ username: '', real_name: '', email: '', department_id: null, password: '' })

onMounted(async () => {
  try {
    departments.value = await api.get('/auth/departments')
    if (departments.value.length > 0) {
      regForm.value.department_id = departments.value[0].id
    }
  } catch (_) {}
})

async function handleLogin() {
  if (!loginForm.value.username || !loginForm.value.password) {
    return ElMessage.warning('请输入用户名和密码')
  }
  loading.value = true
  try {
    const res = await api.post('/auth/login', loginForm.value)
    store.setAuth(res.access_token, res.user)
    ElMessage.success(`欢迎回来，${res.user.real_name}`)
    router.push('/dashboard')
  } finally {
    loading.value = false
  }
}

function quickLogin(username) {
  loginForm.value.username = username
  loginForm.value.password = 'Zju123456'
  handleLogin()
}

async function handleRegister() {
  if (regForm.value.password.length < 8) {
    return ElMessage.warning('密码长度必须至少为 8 个字符')
  }
  loading.value = true
  try {
    const res = await api.post('/auth/register', regForm.value)
    ElMessage.success(res.message)
    loginForm.value.username = regForm.value.username
    loginForm.value.password = regForm.value.password
    activeTab.value = 'login'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
  padding: 16px;
}
.login-box {
  width: 100%;
  max-width: 440px;
  background: #fff;
  border-radius: 16px;
  padding: 28px 24px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
}
.brand-header {
  text-align: center;
  margin-bottom: 20px;
}
.brand-header h2 {
  margin: 0 0 6px;
  color: #1e3a8a;
}
.brand-header p {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}
.demo-accounts {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px dashed #cbd5e1;
}
.demo-title {
  font-size: 12px;
  color: #475569;
  margin-bottom: 10px;
  font-weight: 600;
}
.demo-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
.demo-grid .el-button {
  margin: 0 !important;
  width: 100%;
}
</style>