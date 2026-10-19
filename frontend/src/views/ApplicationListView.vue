<template>
  <div>
    <div class="page-card">
      <!-- 视角切换栏 -->
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 16px;">
        <el-radio-group v-model="viewMode" @change="handleModeChange">
          <el-radio-button value="MY_APPLICATIONS">我的申请</el-radio-button>
          <el-radio-button value="MY_TODOS">我的待办 ({{ store.todoCount }})</el-radio-button>
          <el-radio-button value="MY_DONE">已办事项</el-radio-button>
          <el-radio-button v-if="hasRole('DEPT_MANAGER')" value="DEPT_OVERVIEW">本部门单据</el-radio-button>
          <el-radio-button v-if="hasRole('FINANCE')" value="FINANCE_OVERVIEW">财务单据池</el-radio-button>
          <el-radio-button v-if="hasRole('EXECUTIVE')" value="COMPANY_OVERVIEW">全公司单据</el-radio-button>
        </el-radio-group>

        <el-button type="primary" @click="$router.push('/applications/new')">+ 新建申请</el-button>
      </div>

      <!-- 多条件筛选栏 -->
      <el-row :gutter="10" style="margin-bottom: 14px;">
        <el-col :xs="12" :sm="5">
          <el-select v-model="filters.category" placeholder="全部业务类型" clearable style="width: 100%;" @change="loadData(1)">
            <el-option label="采购审批" value="PROCUREMENT" />
            <el-option label="差旅申请" value="TRAVEL" />
            <el-option label="报销审批" value="EXPENSE" />
            <el-option label="自定义流程" value="CUSTOM" />
          </el-select>
        </el-col>
        <el-col :xs="12" :sm="5">
          <el-select v-model="filters.status" placeholder="全部审批状态" clearable style="width: 100%;" @change="loadData(1)">
            <el-option label="草稿 (DRAFT)" value="DRAFT" />
            <el-option label="审批中 (IN_REVIEW)" value="IN_REVIEW" />
            <el-option label="已通过 (APPROVED)" value="APPROVED" />
            <el-option label="已驳回 (REJECTED)" value="REJECTED" />
            <el-option label="已撤回 (WITHDRAWN)" value="WITHDRAWN" />
          </el-select>
        </el-col>
        <el-col :xs="12" :sm="4">
          <el-date-picker v-model="filters.start_date" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" style="width: 100%;" @change="loadData(1)" />
        </el-col>
        <el-col :xs="12" :sm="4">
          <el-date-picker v-model="filters.end_date" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" style="width: 100%;" @change="loadData(1)" />
        </el-col>
        <el-col :xs="24" :sm="6" style="margin-top: 4px;">
          <el-input v-model="filters.keyword" placeholder="搜索编号或标题关键词" clearable @keyup.enter="loadData(1)">
            <template #append>
              <el-button @click="loadData(1)">查询</el-button>
            </template>
          </el-input>
        </el-col>
      </el-row>

      <!-- 加载与空状态 -->
      <el-skeleton v-if="loading" :rows="5" animated />
      <el-empty v-else-if="items.length === 0" description="当前筛选条件下暂无申请记录" />

      <div v-else>
        <!-- 桌面端表格展示 -->
        <el-table :data="items" border stripe class="desktop-only" style="width: 100%;">
          <el-table-column prop="app_no" label="申请编号" width="175" />
          <el-table-column label="类型" width="105">
            <template #default="{ row }">
              <el-tag size="small">{{ categoryLabel(row.category) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="申请标题" min-width="200">
            <template #default="{ row }">
              <span style="font-weight: 600;">{{ row.title }}</span>
              <el-tag v-if="row.has_risk_warning" type="danger" size="small" style="margin-left: 6px;">异常/预警</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="applicant_name" label="申请人" width="130" />
          <el-table-column prop="department_name" label="所属部门" width="100" />
          <el-table-column label="金额(元)" width="120" align="right">
            <template #default="{ row }">¥ {{ formatAmount(row.total_amount_cents) }}</template>
          </el-table-column>
          <el-table-column label="状态与当前审批人" width="190">
            <template #default="{ row }">
              <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              <div v-if="row.current_approver_name" style="font-size: 12px; color: #64748b; margin-top: 4px;">
                当前待审: {{ row.current_approver_name }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="$router.push(`/applications/${row.id}`)">查看详情</el-button>
              <el-button v-if="row.status === 'DRAFT' && row.applicant_id === store.user?.id" size="small" type="warning" link @click="$router.push(`/applications/${row.id}/edit`)">编辑</el-button>
              <el-button v-if="row.status === 'DRAFT' && row.applicant_id === store.user?.id" size="small" type="danger" link @click="confirmDeleteDraft(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 移动端卡片式触控列表 (无横向滚动) -->
        <div class="mobile-only">
          <div v-for="row in items" :key="row.id" class="mobile-app-card" @click="$router.push(`/applications/${row.id}`)">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="font-size: 12px; color: #64748b;">{{ row.app_no }}</span>
              <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </div>
            <div style="font-weight: 700; font-size: 15px; margin: 8px 0;">
              [{{ categoryLabel(row.category) }}] {{ row.title }}
              <el-tag v-if="row.has_risk_warning" type="danger" size="small">预警</el-tag>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 13px; color: #475569;">
              <span>{{ row.department_name }} · {{ row.applicant_name }}</span>
              <strong style="color: #dc2626;">¥ {{ formatAmount(row.total_amount_cents) }}</strong>
            </div>
            <div v-if="row.current_approver_name" style="font-size: 12px; color: #2563eb; margin-top: 6px;">
              ⏰ 当前审批人：{{ row.current_approver_name }}
            </div>
          </div>
        </div>

        <!-- 分页组件 -->
        <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="loadData"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { formatAmount } from '../api'
import { useAppStore } from '../store'

const route = useRoute()
const router = useRouter()
const store = useAppStore()

const viewMode = ref(route.query.mode || 'MY_APPLICATIONS')
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)

const filters = ref({
  category: '',
  status: '',
  start_date: '',
  end_date: '',
  keyword: ''
})

function hasRole(code) {
  return store.user?.roles?.includes(code)
}

function categoryLabel(c) {
  return { PROCUREMENT: '采购审批', TRAVEL: '差旅申请', EXPENSE: '报销审批', CUSTOM: '自定义' }[c] || c
}

function statusLabel(s) {
  return { DRAFT: '草稿', IN_REVIEW: '审批中', APPROVED: '已通过', REJECTED: '已驳回', WITHDRAWN: '已撤回' }[s] || s
}

function statusTag(s) {
  return { DRAFT: 'info', IN_REVIEW: 'warning', APPROVED: 'success', REJECTED: 'danger', WITHDRAWN: 'info' }[s] || 'info'
}

async function loadData(targetPage = page.value) {
  page.value = targetPage
  loading.value = true
  try {
    const params = {
      view_mode: viewMode.value,
      page: page.value,
      page_size: pageSize.value
    }
    if (filters.value.category) params.category = filters.value.category
    if (filters.value.status) params.status = filters.value.status
    if (filters.value.start_date) params.start_date = filters.value.start_date
    if (filters.value.end_date) params.end_date = filters.value.end_date
    if (filters.value.keyword) params.keyword = filters.value.keyword

    const res = await api.get('/applications', { params })
    items.value = res.items
    total.value = res.total
    store.refreshBadgeCounts()
  } finally {
    loading.value = false
  }
}

function handleModeChange(val) {
  router.replace({ path: '/applications', query: { mode: val } })
  loadData(1)
}

async function confirmDeleteDraft(row) {
  try {
    await ElMessageBox.confirm(`确定要永久删除草稿《${row.title}》吗？删除后不可恢复。`, '删除草稿确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消'
    })
    await api.delete(`/applications/${row.id}`)
    ElMessage.success('草稿已删除')
    loadData(1)
  } catch (_) {}
}

watch(
  () => route.query.mode,
  (newMode) => {
    if (newMode && newMode !== viewMode.value) {
      viewMode.value = newMode
      loadData(1)
    }
  }
)

onMounted(() => loadData(1))
</script>