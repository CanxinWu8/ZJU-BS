<template>
  <div>
    <!-- 顶部欢迎与快捷发起入口 -->
    <div class="page-card welcome-banner">
      <div>
        <h3 style="margin: 0 0 6px;">你好，{{ store.user?.real_name }}（{{ store.user?.department_name }}）</h3>
        <div style="font-size: 13px; color: #64748b;">
          当前拥有角色：
          <el-tag v-for="r in store.user?.roles" :key="r" size="small" style="margin-right: 6px;">{{ r }}</el-tag>
        </div>
      </div>
      <div class="quick-actions">
        <el-button type="primary" @click="$router.push('/applications/new?category=PROCUREMENT')">+ 发起采购</el-button>
        <el-button type="success" @click="$router.push('/applications/new?category=TRAVEL')">+ 差旅申请</el-button>
        <el-button type="warning" @click="$router.push('/applications/new?category=EXPENSE')">+ 费用报销</el-button>
        <el-button type="info" @click="$router.push('/applications/new?category=CUSTOM')">+ 自定义申请</el-button>
      </div>
    </div>

    <!-- 个人待办与通知提醒数字卡片 -->
    <el-row :gutter="12" style="margin-bottom: 16px;">
      <el-col :xs="12" :sm="6">
        <div class="stat-box clickable" @click="$router.push('/applications?mode=MY_TODOS')">
          <div class="stat-label">我的待办审批</div>
          <div class="stat-val danger">{{ statsData?.personal_todo_summary?.my_pending_todo_count || 0 }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-box clickable" @click="$router.push('/applications?mode=MY_DONE')">
          <div class="stat-label">我已处理事项</div>
          <div class="stat-val primary">{{ statsData?.personal_todo_summary?.my_done_count || 0 }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-box clickable" @click="$router.push('/notifications')">
          <div class="stat-label">未读站内通知</div>
          <div class="stat-val warning">{{ statsData?.personal_todo_summary?.my_unread_notify_count || 0 }}</div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="6">
        <div class="stat-box">
          <div class="stat-label">已通过总金额 (元)</div>
          <div class="stat-val success">¥ {{ formatAmount(statsData?.summary_cards?.approved_amount_cents) }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- 统计范围切换与口径说明 -->
    <div class="page-card">
      <div class="scope-header">
        <div>
          <span style="font-weight: 600; margin-right: 12px;">📊 统计维度切换：</span>
          <el-radio-group v-model="currentScope" size="small" @change="loadStats">
            <el-radio-button value="PERSONAL">本人申请</el-radio-button>
            <el-radio-button v-if="hasRole('DEPT_MANAGER')" value="DEPT">本部门统计</el-radio-button>
            <el-radio-button v-if="hasRole('FINANCE')" value="FINANCE">财务专项统计</el-radio-button>
            <el-radio-button v-if="hasRole('EXECUTIVE')" value="COMPANY">全公司统计</el-radio-button>
          </el-radio-group>
        </div>
        <el-button size="small" type="primary" plain @click="openDelegationDialog">
          🤝 审批委托设置 (出差代审)
        </el-button>
      </div>

      <el-alert
        :title="statsData?.caliber_statement || '统计口径加载中...'"
        type="info"
        :closable="false"
        show-icon
        style="margin: 12px 0;"
      />

      <!-- ECharts 双图表展示 -->
      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <div ref="statusChartRef" style="width: 100%; height: 300px;"></div>
        </el-col>
        <el-col :xs="24" :md="12">
          <div ref="categoryChartRef" style="width: 100%; height: 300px;"></div>
        </el-col>
      </el-row>
    </div>

    <!-- 审批委托配置弹窗 (增强功能) -->
    <el-dialog v-model="delegationVisible" title="审批委托代理设置 (增强功能)" width="520px">
      <el-form :model="delForm" label-width="100px">
        <el-form-item label="委托代理人">
          <el-select v-model="delForm.delegatee_id" placeholder="请选择代审同事" style="width: 100%;">
            <el-option v-for="u in availableUsers" :key="u.id" :label="u.real_name" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="生效开始">
          <el-date-picker v-model="delForm.start_time" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="生效结束">
          <el-date-picker v-model="delForm.end_time" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="委托事由">
          <el-input v-model="delForm.reason" placeholder="例如：外出参加学术会议期间委托代审" />
        </el-form-item>
      </el-form>
      <div v-if="myDelegations.length > 0" style="margin-top: 10px; font-size: 12px; color: #64748b;">
        <div>最近委托记录：</div>
        <div v-for="d in myDelegations.slice(0, 3)" :key="d.id" style="margin-top: 4px;">
          • 委托给 <b>{{ d.delegatee_name }}</b> ({{ d.start_time }} ~ {{ d.end_time }}) [{{ d.is_active ? '生效中' : '已停用' }}]
        </div>
      </div>
      <template #footer>
        <el-button @click="delegationVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDelegation">保存并生效</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import api, { formatAmount } from '../api'
import { useAppStore } from '../store'

const store = useAppStore()
const currentScope = ref('PERSONAL')
const statsData = ref(null)
const statusChartRef = ref(null)
const categoryChartRef = ref(null)
let statusChart = null
let categoryChart = null

const delegationVisible = ref(false)
const availableUsers = ref([])
const myDelegations = ref([])
const delForm = ref({
  delegatee_id: null,
  start_time: '2026-10-19T00:00:00',
  end_time: '2026-12-31T23:59:59',
  reason: '出差期间委托代办审批'
})

function hasRole(code) {
  return store.user?.roles?.includes(code)
}

async function loadStats() {
  try {
    statsData.value = await api.get(`/stats/overview?scope=${currentScope.value}`)
    store.todoCount = statsData.value.personal_todo_summary.my_pending_todo_count
    store.unreadCount = statsData.value.personal_todo_summary.my_unread_notify_count
    await nextTick()
    renderCharts()
  } catch (_) {}
}

function renderCharts() {
  if (!statsData.value) return
  if (statusChartRef.value) {
    if (!statusChart) statusChart = echarts.init(statusChartRef.value)
    const dist = statsData.value.charts.status_distribution
    statusChart.setOption({
      title: { text: '申请状态分布', left: 'center', textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'item' },
      legend: { bottom: 0 },
      series: [{
        type: 'pie',
        radius: ['38%', '65%'],
        data: dist.map(i => ({ name: i.label, value: i.count }))
      }]
    })
  }
  if (categoryChartRef.value) {
    if (!categoryChart) categoryChart = echarts.init(categoryChartRef.value)
    const cats = statsData.value.charts.category_breakdown
    categoryChart.setOption({
      title: { text: '各业务申请数量与已通过金额(元)', left: 'center', textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0 },
      xAxis: { type: 'category', data: cats.map(c => c.label) },
      yAxis: [
        { type: 'value', name: '单数', minInterval: 1 },
        { type: 'value', name: '金额(元)' }
      ],
      series: [
        { name: '总申请数', type: 'bar', data: cats.map(c => c.total_count) },
        { name: '已通过金额(元)', type: 'line', yAxisIndex: 1, data: cats.map(c => (c.approved_amount_cents / 100).toFixed(2)) }
      ]
    })
  }
}

async function openDelegationDialog() {
  delegationVisible.value = true
  const res = await api.get('/workflow/delegations')
  availableUsers.value = res.available_users
  myDelegations.value = res.delegations
}

async function saveDelegation() {
  if (!delForm.value.delegatee_id) return ElMessage.warning('请选择代理人')
  const res = await api.post('/workflow/delegations', delForm.value)
  ElMessage.success(res.message)
  delegationVisible.value = false
  loadStats()
}

onMounted(() => {
  loadStats()
  window.addEventListener('resize', () => {
    statusChart?.resize()
    categoryChart?.resize()
  })
})
</script>

<style scoped>
.welcome-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.quick-actions .el-button {
  margin: 0 !important;
}
.stat-box {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-bottom: 10px;
}
.stat-box.clickable {
  cursor: pointer;
}
.stat-label {
  font-size: 13px;
  color: #64748b;
}
.stat-val {
  font-size: 24px;
  font-weight: 700;
  margin-top: 6px;
}
.stat-val.danger { color: #dc2626; }
.stat-val.primary { color: #2563eb; }
.stat-val.warning { color: #d97706; }
.stat-val.success { color: #16a34a; }
.scope-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
</style>