<template>
  <div v-if="detail">
    <!-- 顶部概要与状态卡片 -->
    <div class="page-card">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px;">
        <div>
          <div style="font-size: 13px; color: #64748b; margin-bottom: 4px;">
            申请单号：<b>{{ detail.app_no }}</b> · 版本快照：v{{ detail.version }}
            <span v-if="detail.copied_from_id">（复制重提自原单 #{{ detail.copied_from_id }}）</span>
          </div>
          <h2 style="margin: 0 0 8px;">{{ detail.title }}</h2>
          <div style="font-size: 13px; color: #475569;">
            申请人：<b>{{ detail.applicant_name }}</b>（{{ detail.department_name }}） · 提交时间：{{ formatTime(detail.submitted_at || detail.created_at) }}
          </div>
        </div>
        <div style="text-align: right;">
          <el-tag :type="statusTag(detail.status)" size="large" effect="dark">{{ statusLabel(detail.status) }}</el-tag>
          <div style="font-size: 22px; font-weight: 700; color: #dc2626; margin-top: 8px;">
            ¥ {{ formatAmount(detail.total_amount_cents) }}
          </div>
        </div>
      </div>

      <!-- 风险预警横幅（单一来源采购 / 未选最低价 / 无票异常支出 / 跨单重复票据预警） -->
      <el-alert
        v-if="detail.has_risk_warning"
        type="warning"
        show-icon
        :closable="false"
        style="margin-top: 14px;"
        title="⚠️ 审批合规重点核查提醒：本单包含【单一来源采购 / 未选最低价供应商 / 无票异常支出 / 跨单疑似重复发票】，请审批人重点核查下方高亮项！"
      />

      <!-- 跨单重复发票预警详情展示 -->
      <el-alert
        v-if="detail.biz_payload?.duplicate_invoice_warnings?.length"
        type="error"
        :closable="false"
        style="margin-top: 10px;"
      >
        <template #title>
          <div>🚨 跨申请重复票据智能预警（SHA-256 哈希 / 发票号碰撞）：</div>
          <div v-for="(w, i) in detail.biz_payload.duplicate_invoice_warnings" :key="i" style="font-size: 12px; margin-top: 4px;">
            • 命中历史单据：<b>{{ w.matched_app_no }}</b>（上传人：{{ w.uploaded_by_name }}，原因：{{ w.reason }}）
          </div>
        </template>
      </el-alert>

      <!-- 审批人 / 申请人操作按钮组 -->
      <div class="action-toolbar">
        <!-- 当前节点审批人操作 -->
        <template v-if="isCurrentApprover">
          <el-button type="success" size="large" @click="handleApprove">✅ 批准通过</el-button>
          <el-button type="danger" size="large" @click="handleReject">❌ 驳回申请 (必填理由)</el-button>
        </template>

        <!-- 申请人本人操作 -->
        <template v-if="isApplicant">
          <el-button v-if="detail.status === 'DRAFT'" type="primary" @click="$router.push(`/applications/${detail.id}/edit`)">✏️ 继续编辑草稿</el-button>
          <el-button v-if="detail.status === 'IN_REVIEW'" type="warning" plain @click="handleUrge">⚡ 一键催办当前节点</el-button>
          <el-button v-if="detail.status === 'IN_REVIEW'" type="danger" plain @click="handleWithdraw">↩️ 撤回申请</el-button>
          <el-button v-if="['REJECTED', 'WITHDRAWN'].includes(detail.status)" type="primary" @click="handleResubmitCopy">
            📋 复制修改并重新提交
          </el-button>
        </template>

        <el-button size="default" @click="loadDetail">🔄 刷新最新状态</el-button>
      </div>
    </div>

    <!-- 固化审批路径节点进度 -->
    <div v-if="detail.nodes?.length" class="page-card">
      <h4 style="margin: 0 0 14px;">🛤️ 审批流转路径（提交时固化快照）</h4>
      <el-steps :active="activeStepIndex" finish-status="success">
        <el-step
          v-for="n in detail.nodes"
          :key="n.id"
          :title="`${n.node_seq}. ${n.node_name}`"
          :status="stepStatus(n.status)"
          :description="`${n.approver_name}${n.delegated_from_name ? `(由${n.delegated_from_name}委托)` : ''} [${n.status}] ${n.comment ? '意见:' + n.comment : ''}`"
        />
      </el-steps>
    </div>

    <!-- 业务正文与多行明细展示 -->
    <div class="page-card">
      <h4 style="margin: 0 0 14px;">📄 申请业务正文与明细</h4>

      <!-- 1. 采购详情 -->
      <div v-if="detail.category === 'PROCUREMENT'">
        <p><b>采购原因：</b>{{ detail.biz_payload?.reason }} | <b>期望到货：</b>{{ detail.biz_payload?.expected_date }} | <b>所属项目：</b>{{ detail.biz_payload?.project_name || '无' }}</p>
        <el-alert v-if="detail.biz_payload?.is_single_source" type="warning" :closable="false" :title="`单一来源采购说明：${detail.biz_payload.single_source_reason}`" style="margin-bottom: 10px;" />
        <el-alert v-if="detail.biz_payload?.non_lowest_reason" type="warning" :closable="false" :title="`未选最低价供应商理由：${detail.biz_payload.non_lowest_reason}`" style="margin-bottom: 10px;" />

        <h5>采购明细清单</h5>
        <el-table :data="detail.procurement_items" border size="small" style="margin-bottom: 14px;">
          <el-table-column prop="item_name" label="名称" />
          <el-table-column prop="specification" label="规格" />
          <el-table-column prop="quantity" label="数量" width="80" />
          <el-table-column prop="unit" label="单位" width="70" />
          <el-table-column label="单价(元)" width="110">
            <template #default="{ row }">¥ {{ formatAmount(row.unit_price_cents) }}</template>
          </el-table-column>
          <el-table-column label="小计(元)" width="120">
            <template #default="{ row }">¥ {{ formatAmount(row.subtotal_cents) }}</template>
          </el-table-column>
        </el-table>

        <h5>供应商比价记录</h5>
        <el-table :data="detail.procurement_quotes" border size="small">
          <el-table-column prop="supplier_name" label="供应商名称" />
          <el-table-column prop="quote_date" label="报价日期" width="120" />
          <el-table-column label="报价金额(元)" width="130">
            <template #default="{ row }">¥ {{ formatAmount(row.quoted_amount_cents) }}</template>
          </el-table-column>
          <el-table-column label="是否拟选" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.is_selected" type="success" size="small">拟选供应商</el-tag>
              <span v-else>备选</span>
            </template>
          </el-table-column>
          <el-table-column prop="purchase_url" label="链接/依据" />
        </el-table>
      </div>

      <!-- 2. 差旅详情 -->
      <div v-else-if="detail.category === 'TRAVEL'">
        <p><b>行程路线：</b>{{ detail.biz_payload?.departure }} → {{ detail.biz_payload?.destination }}</p>
        <p><b>起止日期：</b>{{ detail.biz_payload?.start_date }} 至 {{ detail.biz_payload?.end_date }}（共 <b>{{ detail.biz_payload?.duration_days }}</b> 天，{{ detail.biz_payload?.duration_caliber }}）</p>
        <p><b>交通工具：</b>{{ detail.biz_payload?.transport }} | <b>同行人员：</b>{{ detail.biz_payload?.companions || '无' }}</p>
        <p><b>出差事由：</b>{{ detail.biz_payload?.purpose }}</p>
      </div>

      <!-- 3. 报销详情 -->
      <div v-else-if="detail.category === 'EXPENSE'">
        <p><b>报销说明：</b>{{ detail.biz_payload?.expense_desc }}</p>
        <el-alert
          v-if="detail.ref_application"
          type="success"
          :closable="false"
          style="margin-bottom: 12px;"
          :title="`🔗 已关联前置批准申请：[${detail.ref_application.app_no}] ${detail.ref_application.title}（原批准金额：¥${formatAmount(detail.ref_application.total_amount_cents)}）`"
        />
        <el-table :data="detail.expense_items" border size="small">
          <el-table-column prop="expense_type" label="费用类型" width="100" />
          <el-table-column prop="occur_date" label="发生日期" width="115" />
          <el-table-column prop="description" label="用途说明" />
          <el-table-column label="金额(元)" width="120">
            <template #default="{ row }">¥ {{ formatAmount(row.amount_cents) }}</template>
          </el-table-column>
          <el-table-column label="票据状态与财务核查提示" min-width="220">
            <template #default="{ row }">
              <div v-if="row.is_no_invoice" style="color: #dc2626; font-weight: 700;">
                🚨 【无票异常支出】原因：{{ row.no_invoice_reason }}
              </div>
              <div v-else>
                <el-tag type="success" size="small">已附合规票据</el-tag>
                <span v-if="row.invoice_numbers" style="font-size: 12px; margin-left: 6px;">票号: {{ row.invoice_numbers }}</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 4. 自定义流程详情 -->
      <div v-else-if="detail.category === 'CUSTOM'">
        <div v-for="(val, key) in detail.biz_payload" :key="key" style="margin-bottom: 8px;">
          <b>{{ key }}：</b> <span>{{ val }}</span>
        </div>
      </div>

      <!-- 附件与票据受控预览/下载区 -->
      <div style="margin-top: 18px; padding-top: 12px; border-top: 1px solid #e2e8f0;">
        <h5 style="margin: 0 0 10px;">📎 关联附件与电子票据（服务端强鉴权访问）</h5>
        <div v-if="detail.attachments?.length === 0" style="font-size: 13px; color: #94a3b8;">无上传附件</div>
        <div v-for="att in detail.attachments" :key="att.id" class="att-row">
          <div>
            <el-tag size="small" style="margin-right: 6px;">{{ att.file_category }}</el-tag>
            <b>{{ att.original_name }}</b>
            <span style="font-size: 12px; color: #64748b; margin-left: 8px;">
              ({{ (att.file_size_bytes / 1024).toFixed(1) }} KB · 上传人: {{ att.uploaded_by_name }}
              <span v-if="att.invoice_no"> · 发票号: {{ att.invoice_no }}</span>)
            </span>
          </div>
          <div>
            <el-button size="small" type="primary" link @click="openProtectedFile(att.id, false)">在线预览</el-button>
            <el-button size="small" type="success" link @click="openProtectedFile(att.id, true)">安全下载</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 不可篡改审批日志时间线 -->
    <div class="page-card">
      <h4 style="margin: 0 0 14px;">📜 审批与操作留痕日志（不可修改/不可删除）</h4>
      <el-timeline>
        <el-timeline-item
          v-for="l in detail.logs"
          :key="l.id"
          :timestamp="formatTime(l.created_at)"
          :type="l.action === 'REJECT' ? 'danger' : l.action === 'APPROVE' ? 'success' : 'primary'"
        >
          <b>[{{ l.action }}] {{ l.node_name }}</b> — 操作人：{{ l.operator_name }}
          <div style="font-size: 13px; color: #475569; margin-top: 4px;">
            意见/详情：{{ l.comment }} （结果状态：{{ l.result_status }}）
          </div>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import api, { formatAmount } from '../api'
import { useAppStore } from '../store'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const detail = ref(null)

const isApplicant = computed(() => detail.value && detail.value.applicant_id === store.user?.id)
const isCurrentApprover = computed(() => {
  if (!detail.value || detail.value.status !== 'IN_REVIEW') return false
  const pendingNode = detail.value.nodes?.find(n => n.status === 'PENDING')
  return pendingNode && pendingNode.approver_id === store.user?.id
})

const activeStepIndex = computed(() => {
  if (!detail.value?.nodes) return 0
  if (detail.value.status === 'APPROVED') return detail.value.nodes.length
  const idx = detail.value.nodes.findIndex(n => n.status === 'PENDING')
  return idx >= 0 ? idx : 0
})

function statusLabel(s) {
  return { DRAFT: '草稿', IN_REVIEW: '审批中', APPROVED: '已通过', REJECTED: '已驳回', WITHDRAWN: '已撤回' }[s] || s
}

function statusTag(s) {
  return { DRAFT: 'info', IN_REVIEW: 'warning', APPROVED: 'success', REJECTED: 'danger', WITHDRAWN: 'info' }[s] || 'info'
}

function stepStatus(s) {
  return { APPROVED: 'success', REJECTED: 'error', PENDING: 'process', WAITING: 'wait', CANCELED: 'wait' }[s] || 'wait'
}

function formatTime(t) {
  return t ? t.replace('T', ' ').slice(0, 19) : ''
}

async function loadDetail() {
  detail.value = await api.get(`/applications/${route.params.id}`)
  store.refreshBadgeCounts()
}

async function handleApprove() {
  try {
    const { value } = await ElMessageBox.prompt('请输入审批同意意见（选填）：', '批准通过确认', {
      confirmButtonText: '确认批准',
      cancelButtonText: '取消',
      inputValue: '审核通过，同意申请'
    })
    const res = await api.post(`/workflow/applications/${detail.value.id}/approve`, {
      comment: value || '同意',
      expected_version: detail.value.version
    })
    ElMessage.success(res.message)
    loadDetail()
  } catch (_) {}
}

async function handleReject() {
  try {
    const { value } = await ElMessageBox.prompt('驳回申请必须填写明确理由：', '驳回申请确认', {
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
      inputValidator: (val) => (val && val.trim().length > 0) ? true : '驳回理由不能为空！'
    })
    const res = await api.post(`/workflow/applications/${detail.value.id}/reject`, {
      comment: value,
      expected_version: detail.value.version
    })
    ElMessage.warning(res.message)
    loadDetail()
  } catch (_) {}
}

async function handleWithdraw() {
  try {
    await ElMessageBox.confirm('确定要撤回该审批中的申请吗？撤回后当前待办将立即失效。', '撤回申请确认', {
      type: 'warning',
      confirmButtonText: '确认撤回',
      cancelButtonText: '取消'
    })
    const res = await api.post(`/workflow/applications/${detail.value.id}/withdraw`, {
      reason: '申请人主动撤回修改',
      expected_version: detail.value.version
    })
    ElMessage.success(res.message)
    loadDetail()
  } catch (_) {}
}

async function handleUrge() {
  const res = await api.post(`/workflow/applications/${detail.value.id}/urge`, {
    message: '业务紧急，恳请尽快协助审批！'
  })
  ElMessage.success(res.message)
  loadDetail()
}

async function handleResubmitCopy() {
  const res = await api.post(`/workflow/applications/${detail.value.id}/resubmit-copy`)
  ElMessage.success(res.message)
  router.push(`/applications/${res.new_application_id}/edit`)
}

async function openProtectedFile(attId, isDownload) {
  try {
    const response = await axios.get(`/api/v1/attachments/${attId}/file?download=${isDownload}`, {
      responseType: 'blob',
      headers: { Authorization: `Bearer ${store.token}` }
    })
    const blobUrl = URL.createObjectURL(response.data)
    if (isDownload) {
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = `attachment_${attId}`
      a.click()
    } else {
      window.open(blobUrl, '_blank')
    }
  } catch (_) {
    ElMessage.error('无权访问该附件或文件不存在')
  }
}

onMounted(loadDetail)
</script>

<style scoped>
.action-toolbar {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed #cbd5e1;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.att-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
  margin-bottom: 6px;
}
</style>