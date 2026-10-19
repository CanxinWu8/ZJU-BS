<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">{{ editId ? '📝 编辑申请草稿' : '✍️ 发起审批申请' }}</h3>
      <el-button size="small" @click="$router.back()">返回</el-button>
    </div>

    <el-form label-position="top">
      <!-- 1. 选择流程模板与申请标题 -->
      <el-row :gutter="16">
        <el-col :xs="24" :sm="10">
          <el-form-item label="选择审批流程模板" required>
            <el-select v-model="selectedTemplateCode" style="width: 100%;" :disabled="!!editId" @change="onTemplateChange">
              <el-option
                v-for="t in templates"
                :key="t.code"
                :label="`[${categoryLabel(t.category)}] ${t.name} (v${t.current_version})`"
                :value="t.code"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="14">
          <el-form-item label="申请单标题" required>
            <el-input v-model="form.title" placeholder="请输入清晰明确的申请标题，例如：2026秋季研发服务器采购申请" />
          </el-form-item>
        </el-col>
      </el-row>

      <!-- 当前模板审批路径预览 -->
      <el-alert v-if="currentTemplate" type="info" :closable="false" style="margin-bottom: 16px;">
        <template #title>
          <span>📌 流程节点规则预览：</span>
          <span v-for="(n, idx) in currentTemplate.nodes_config" :key="n.node_seq">
            <b>{{ idx + 1 }}. {{ n.node_name }}</b>
            <span v-if="n.min_amount_cents > 0">(满¥{{ n.min_amount_cents / 100 }}触发)</span>
            <span v-if="idx < currentTemplate.nodes_config.length - 1"> → </span>
          </span>
        </template>
      </el-alert>

      <!-- ==================== A. 采购审批专属表单 ==================== -->
      <div v-if="currentCategory === 'PROCUREMENT'">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="8">
            <el-form-item label="期望到货日期" required>
              <el-date-picker v-model="form.biz_payload.expected_date" type="date" value-format="YYYY-MM-DD" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="所属部门或专项项目">
              <el-input v-model="form.biz_payload.project_name" placeholder="如：AI大模型安全评测专项" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="预算上限 (元)" required>
              <el-input-number v-model="budgetLimitYuan" :min="1" :precision="2" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="采购原因与用途说明" required>
          <el-input v-model="form.biz_payload.reason" type="textarea" :rows="2" placeholder="请详细说明采购用途与必要性" />
        </el-form-item>

        <!-- 采购明细列表 (支持增删，至少2条) -->
        <div class="sub-section">
          <div class="sub-header">
            <strong>📦 采购物品/服务明细（提交时至少需 2 条，合计：¥ {{ formatAmount(computedTotalCents) }}）</strong>
            <el-button size="small" type="primary" plain @click="addProcItem">+ 新增采购明细</el-button>
          </div>
          <div v-for="(item, idx) in form.procurement_items" :key="idx" class="sub-card">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
              <b>明细项 #{{ idx + 1 }}（小计：¥ {{ ((item.quantity || 0) * (item.unit_price_yuan || 0)).toFixed(2) }}）</b>
              <el-button v-if="form.procurement_items.length > 2" size="small" type="danger" link @click="form.procurement_items.splice(idx, 1)">删除</el-button>
            </div>
            <el-row :gutter="10">
              <el-col :xs="24" :sm="7">
                <el-input v-model="item.item_name" placeholder="物品/服务名称" />
              </el-col>
              <el-col :xs="12" :sm="6">
                <el-input v-model="item.specification" placeholder="规格型号" />
              </el-col>
              <el-col :xs="12" :sm="3">
                <el-input v-model="item.unit" placeholder="单位(台/件)" />
              </el-col>
              <el-col :xs="12" :sm="4">
                <el-input-number v-model="item.quantity" :min="1" style="width: 100%;" placeholder="数量" />
              </el-col>
              <el-col :xs="12" :sm="4">
                <el-input-number v-model="item.unit_price_yuan" :min="0.01" :precision="2" style="width: 100%;" placeholder="单价(元)" />
              </el-col>
            </el-row>
          </div>
        </div>

        <!-- 供应商比价 (至少2家，或开启单一来源说明) -->
        <div class="sub-section">
          <div class="sub-header">
            <div>
              <strong>🏢 供应商报价比较</strong>
              <el-checkbox v-model="form.biz_payload.is_single_source" style="margin-left: 14px;">单一来源采购例外</el-checkbox>
            </div>
            <el-button size="small" type="success" plain @click="addProcQuote">+ 新增供应商报价</el-button>
          </div>

          <el-form-item v-if="form.biz_payload.is_single_source" label="⚠️ 单一来源采购详细说明 (必填，将在审批界面醒目展示)" required>
            <el-input v-model="form.biz_payload.single_source_reason" type="textarea" placeholder="请说明为何无法提供两家及以上报价（如独家专利授权、原厂配套维保等）" />
          </el-form-item>

          <div v-for="(q, idx) in form.procurement_quotes" :key="idx" class="sub-card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <el-radio v-model="selectedQuoteIndex" :value="idx">设为拟选供应商</el-radio>
              <el-button v-if="form.procurement_quotes.length > 1" size="small" type="danger" link @click="form.procurement_quotes.splice(idx, 1)">删除</el-button>
            </div>
            <el-row :gutter="10">
              <el-col :xs="24" :sm="6">
                <el-input v-model="q.supplier_name" placeholder="供应商名称" />
              </el-col>
              <el-col :xs="12" :sm="5">
                <el-date-picker v-model="q.quote_date" type="date" value-format="YYYY-MM-DD" placeholder="报价日期" style="width: 100%;" />
              </el-col>
              <el-col :xs="12" :sm="5">
                <el-input-number v-model="q.quoted_amount_yuan" :min="0.01" :precision="2" style="width: 100%;" placeholder="报价总额(元)" />
              </el-col>
              <el-col :xs="24" :sm="8">
                <el-input v-model="q.purchase_url" placeholder="电商购买链接或备注" />
              </el-col>
            </el-row>
            <div style="margin-top: 8px; display: flex; align-items: center; gap: 10px;">
              <input type="file" accept="image/jpeg,image/png,application/pdf" @change="(e) => uploadQuoteFile(e, q)" />
              <el-tag v-if="q.attachment_id" type="success" size="small">已上传报价凭证 #{{ q.attachment_id }}</el-tag>
            </div>
          </div>

          <el-form-item v-if="isNonLowestSelected" label="⚠️ 您选择的供应商报价高于最低报价，必须说明【未选最低价理由】" required>
            <el-input v-model="form.biz_payload.non_lowest_reason" placeholder="请说明未选最低价供应商的具体原因（如交期、正品授权、售后质保等）" />
          </el-form-item>
        </div>
      </div>

      <!-- ==================== B. 差旅申请专属表单 ==================== -->
      <div v-else-if="currentCategory === 'TRAVEL'">
        <el-row :gutter="14">
          <el-col :xs="12" :sm="6">
            <el-form-item label="出发地点" required>
              <el-input v-model="form.biz_payload.departure" placeholder="如：杭州" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="目的地点" required>
              <el-input v-model="form.biz_payload.destination" placeholder="如：北京" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="开始日期" required>
              <el-date-picker v-model="form.biz_payload.start_date" type="date" value-format="YYYY-MM-DD" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="结束日期" required>
              <el-date-picker v-model="form.biz_payload.end_date" type="date" value-format="YYYY-MM-DD" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-alert
          :title="`📅 系统自动计算时长：${travelDurationDays} 天（计算口径：自然日口径 = 结束日期 - 开始日期 + 1天）`"
          type="success"
          :closable="false"
          style="margin-bottom: 14px;"
        />

        <el-row :gutter="14">
          <el-col :xs="24" :sm="8">
            <el-form-item label="交通方式" required>
              <el-select v-model="form.biz_payload.transport" style="width: 100%;">
                <el-option label="高铁/动车" value="高铁" />
                <el-option label="飞机" value="飞机" />
                <el-option label="大巴/自驾" value="大巴/自驾" />
                <el-option label="其他" value="其他" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="同行人员 (选填)">
              <el-input v-model="form.biz_payload.companions" placeholder="可填同事姓名或外部同行人" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="预计费用预算 (元，不得为负数)" required>
              <el-input-number v-model="travelBudgetYuan" :min="0" :precision="2" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="出差目的与行程安排说明" required>
          <el-input v-model="form.biz_payload.purpose" type="textarea" :rows="3" placeholder="请说明出差具体任务及日程安排" />
        </el-form-item>
      </div>

      <!-- ==================== C. 报销审批专属表单 ==================== -->
      <div v-else-if="currentCategory === 'EXPENSE'">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="12">
            <el-form-item label="关联本人已批准的差旅或采购申请 (可留空作为独立报销)">
              <el-select v-model="form.ref_application_id" clearable placeholder="独立日常报销（不关联前置单据）" style="width: 100%;">
                <el-option
                  v-for="la in linkableApps"
                  :key="la.id"
                  :label="`[${la.app_no}] ${la.title} (批准预算: ¥${formatAmount(la.total_amount_cents)})`"
                  :value="la.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="报销说明 / 独立报销事由" required>
              <el-input v-model="form.biz_payload.expense_desc" placeholder="请说明本次费用报销事由" />
            </el-form-item>
          </el-col>
        </el-row>

        <div class="sub-section">
          <div class="sub-header">
            <strong>🧾 报销费用明细（提交时至少需 3 条，实时合计：¥ {{ formatAmount(computedTotalCents) }}）</strong>
            <el-button size="small" type="primary" plain @click="addExpenseItem">+ 新增费用明细</el-button>
          </div>

          <div v-for="(exp, idx) in form.expense_items" :key="idx" class="sub-card">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
              <b>费用项 #{{ idx + 1 }}</b>
              <el-button v-if="form.expense_items.length > 3" size="small" type="danger" link @click="form.expense_items.splice(idx, 1)">删除</el-button>
            </div>
            <el-row :gutter="10">
              <el-col :xs="12" :sm="5">
                <el-select v-model="exp.expense_type" style="width: 100%;">
                  <el-option label="交通费 (TRAFFIC)" value="TRAFFIC" />
                  <el-option label="住宿费 (HOTEL)" value="HOTEL" />
                  <el-option label="餐饮费 (MEAL)" value="MEAL" />
                  <el-option label="办公费 (OFFICE)" value="OFFICE" />
                  <el-option label="其他 (OTHER)" value="OTHER" />
                </el-select>
              </el-col>
              <el-col :xs="12" :sm="5">
                <el-date-picker v-model="exp.occur_date" type="date" value-format="YYYY-MM-DD" placeholder="发生日期" style="width: 100%;" />
              </el-col>
              <el-col :xs="24" :sm="9">
                <el-input v-model="exp.description" placeholder="费用具体用途说明" />
              </el-col>
              <el-col :xs="24" :sm="5">
                <el-input-number v-model="exp.amount_yuan" :min="0.01" :precision="2" style="width: 100%;" placeholder="金额(元)" />
              </el-col>
            </el-row>

            <!-- 票据上传或无票例外 -->
            <div style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed #e2e8f0;">
              <el-checkbox v-model="exp.is_no_invoice">无票支出例外（将在财务审核界面高亮展示）</el-checkbox>
              <div v-if="exp.is_no_invoice" style="margin-top: 6px;">
                <el-input v-model="exp.no_invoice_reason" placeholder="必填：请说明无票支出的具体原因" />
              </div>
              <div v-else style="margin-top: 6px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px;">
                <el-input v-model="exp.temp_invoice_no" placeholder="选填：发票号码(用于查重)" style="width: 190px;" size="small" />
                <!-- capture="environment" 支持手机直接唤起摄像头拍照上传发票 -->
                <input type="file" accept="image/jpeg,image/png,application/pdf" capture="environment" @change="(e) => uploadExpenseInvoice(e, exp)" />
                <el-tag v-for="aid in exp.attachment_ids" :key="aid" type="success" size="small">
                  已绑票据 #{{ aid }}
                </el-tag>
              </div>
              <el-alert
                v-if="exp.dup_warnings && exp.dup_warnings.length > 0"
                type="error"
                :closable="false"
                style="margin-top: 6px;"
                :title="`⚠️ 跨单重复票据预警：该发票与历史单据 ${exp.dup_warnings[0].matched_app_no} (${exp.dup_warnings[0].reason}) 重复！`"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== D. 管理员自定义流程动态表单渲染 ==================== -->
      <div v-else-if="currentCategory === 'CUSTOM' && currentTemplate">
        <div class="sub-section">
          <div class="sub-header">
            <strong>🧩 动态表单字段（由管理员模板 v{{ currentTemplate.current_version }} 实时驱动渲染）</strong>
          </div>
          <el-row :gutter="14">
            <el-col v-for="field in currentTemplate.form_schema?.fields || []" :key="field.field_key" :xs="24" :sm="field.type === 'textarea' ? 24 : 12">
              <el-form-item :label="field.label" :required="field.required">
                <el-input v-if="field.type === 'text'" v-model="form.biz_payload[field.field_key]" />
                <el-input v-else-if="field.type === 'textarea'" v-model="form.biz_payload[field.field_key]" type="textarea" :rows="3" />
                <el-input-number v-else-if="field.type === 'number'" v-model="form.biz_payload[field.field_key]" style="width: 100%;" />
                <el-date-picker v-else-if="field.type === 'date'" v-model="form.biz_payload[field.field_key]" type="date" value-format="YYYY-MM-DD" style="width: 100%;" />
                <el-radio-group v-else-if="field.type === 'radio'" v-model="form.biz_payload[field.field_key]">
                  <el-radio v-for="opt in field.options || []" :key="opt" :value="opt">{{ opt }}</el-radio>
                </el-radio-group>
                <div v-else-if="field.type === 'file'">
                  <input type="file" accept="image/jpeg,image/png,application/pdf" @change="(e) => uploadCustomFieldFile(e, field.field_key)" />
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </div>
      </div>

      <!-- 通用补充附件上传 -->
      <el-form-item label="📎 补充说明附件 (支持 JPEG / PNG / PDF，单文件 <= 10MB)">
        <input type="file" accept="image/jpeg,image/png,application/pdf" @change="uploadGeneralAttachment" />
        <div style="margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap;">
          <el-tag v-for="aid in form.attachment_ids" :key="aid" closable @close="removeGeneralAtt(aid)">附件 #{{ aid }}</el-tag>
        </div>
      </el-form-item>

      <!-- 底部提交与保存草稿操作栏 -->
      <div class="submit-bar">
        <div style="font-size: 16px; font-weight: 700; color: #1e3a8a;">
          系统核算合计金额：¥ {{ formatAmount(computedTotalCents) }}
        </div>
        <div style="display: flex; gap: 10px;">
          <el-button size="large" :loading="submitting" @click="submitForm('SAVE_DRAFT')">💾 保存草稿</el-button>
          <el-button type="primary" size="large" :loading="submitting" @click="submitForm('SUBMIT')">🚀 校验并正式提交</el-button>
        </div>
      </div>
    </el-form>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api, { formatAmount } from '../api'

const route = useRoute()
const router = useRouter()
const editId = computed(() => route.params.id ? Number(route.params.id) : null)

const templates = ref([])
const linkableApps = ref([])
const selectedTemplateCode = ref('PROCUREMENT_STD')
const submitting = ref(false)

const budgetLimitYuan = ref(6000)
const travelBudgetYuan = ref(1800)
const selectedQuoteIndex = ref(0)

const form = ref({
  id: null,
  title: '',
  ref_application_id: null,
  biz_payload: {
    expected_date: '2026-11-10',
    project_name: '',
    reason: '',
    is_single_source: false,
    single_source_reason: '',
    non_lowest_reason: '',
    departure: '杭州',
    destination: '上海',
    start_date: '2026-11-01',
    end_date: '2026-11-03',
    transport: '高铁',
    companions: '',
    purpose: '',
    expense_desc: ''
  },
  attachment_ids: [],
  procurement_items: [
    { item_name: '高性能固态硬盘', specification: '2TB NVMe', quantity: 2, unit: '块', unit_price_yuan: 800 },
    { item_name: 'DDR5服务器内存', specification: '64GB ECC', quantity: 2, unit: '根', unit_price_yuan: 1200 }
  ],
  procurement_quotes: [
    { supplier_name: '数码专营供应商A', quote_date: '2026-10-19', quoted_amount_yuan: 3900, purchase_url: '', attachment_id: null },
    { supplier_name: '京东企业自营B', quote_date: '2026-10-19', quoted_amount_yuan: 4000, purchase_url: 'https://jd.com', attachment_id: null }
  ],
  expense_items: [
    { expense_type: 'TRAFFIC', occur_date: '2026-10-18', description: '往返高铁二等座车票', amount_yuan: 450, is_no_invoice: false, no_invoice_reason: '', attachment_ids: [], temp_invoice_no: '', dup_warnings: [] },
    { expense_type: 'HOTEL', occur_date: '2026-10-18', description: '出差酒店住宿费2晚', amount_yuan: 680, is_no_invoice: false, no_invoice_reason: '', attachment_ids: [], temp_invoice_no: '', dup_warnings: [] },
    { expense_type: 'MEAL', occur_date: '2026-10-19', description: '出差误餐补贴', amount_yuan: 160, is_no_invoice: true, no_invoice_reason: '按公司定额误餐补贴标准发放，免贴票据', attachment_ids: [], temp_invoice_no: '', dup_warnings: [] }
  ]
})

const currentTemplate = computed(() => templates.value.find(t => t.code === selectedTemplateCode.value))
const currentCategory = computed(() => currentTemplate.value?.category || 'PROCUREMENT')

function categoryLabel(c) {
  return { PROCUREMENT: '采购', TRAVEL: '差旅', EXPENSE: '报销', CUSTOM: '自定义' }[c] || c
}

const computedTotalCents = computed(() => {
  if (currentCategory.value === 'PROCUREMENT') {
    return form.value.procurement_items.reduce((sum, i) => sum + Math.round((i.quantity || 0) * (i.unit_price_yuan || 0) * 100), 0)
  }
  if (currentCategory.value === 'TRAVEL') {
    return Math.round((travelBudgetYuan.value || 0) * 100)
  }
  if (currentCategory.value === 'EXPENSE') {
    return form.value.expense_items.reduce((sum, e) => sum + Math.round((e.amount_yuan || 0) * 100), 0)
  }
  return 0
})

const isNonLowestSelected = computed(() => {
  if (currentCategory.value !== 'PROCUREMENT' || form.value.procurement_quotes.length < 2) return false
  const quotes = form.value.procurement_quotes
  const minVal = Math.min(...quotes.map(q => Number(q.quoted_amount_yuan || 0)))
  const chosen = quotes[selectedQuoteIndex.value]
  return chosen && Number(chosen.quoted_amount_yuan || 0) > minVal
})

const travelDurationDays = computed(() => {
  const s = form.value.biz_payload.start_date
  const e = form.value.biz_payload.end_date
  if (!s || !e) return 0
  const diff = (new Date(e) - new Date(s)) / (1000 * 3600 * 24)
  return diff >= 0 ? Math.round(diff) + 1 : -1
})

function onTemplateChange() {
  if (!editId.value && currentTemplate.value) {
    form.value.title = `${currentTemplate.value.name} - ${new Date().toISOString().slice(0, 10)}`
  }
}

function addProcItem() {
  form.value.procurement_items.push({ item_name: '', specification: '', quantity: 1, unit: '件', unit_price_yuan: 100 })
}

function addProcQuote() {
  form.value.procurement_quotes.push({ supplier_name: '', quote_date: '2026-10-19', quoted_amount_yuan: 1000, purchase_url: '', attachment_id: null })
}

function addExpenseItem() {
  form.value.expense_items.push({ expense_type: 'OTHER', occur_date: '2026-10-19', description: '', amount_yuan: 100, is_no_invoice: false, no_invoice_reason: '', attachment_ids: [], temp_invoice_no: '', dup_warnings: [] })
}

async function uploadFileHelper(file, category, invoiceNo = '') {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('file_category', category)
  if (invoiceNo) fd.append('invoice_no', invoiceNo)
  return await api.post('/attachments/upload', fd)
}

async function uploadQuoteFile(e, quoteObj) {
  const file = e.target.files?.[0]
  if (!file) return
  const res = await uploadFileHelper(file, 'QUOTE_PROOF')
  quoteObj.attachment_id = res.id
  ElMessage.success(`报价凭证 ${res.original_name} 上传成功`)
}

async function uploadExpenseInvoice(e, expObj) {
  const file = e.target.files?.[0]
  if (!file) return
  const res = await uploadFileHelper(file, 'INVOICE', expObj.temp_invoice_no)
  expObj.attachment_ids.push(res.id)
  if (res.has_duplicate_warning) {
    expObj.dup_warnings = res.duplicate_warnings
    ElMessage.warning('⚠️ 检测到该票据与历史报销单存在重复，已标记预警！')
  } else {
    ElMessage.success(`票据 ${res.original_name} 上传成功`)
  }
}

async function uploadCustomFieldFile(e, fieldKey) {
  const file = e.target.files?.[0]
  if (!file) return
  const res = await uploadFileHelper(file, 'CUSTOM_ATTACHMENT')
  form.value.biz_payload[fieldKey] = `附件#${res.id}:${res.original_name}`
  form.value.attachment_ids.push(res.id)
  ElMessage.success('自定义字段附件已上传')
}

async function uploadGeneralAttachment(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const res = await uploadFileHelper(file, 'TRAVEL_DOC')
  form.value.attachment_ids.push(res.id)
  ElMessage.success(`附件 ${res.original_name} 上传成功`)
}

function removeGeneralAtt(id) {
  form.value.attachment_ids = form.value.attachment_ids.filter(i => i !== id)
}

async function submitForm(actionType) {
  if (!form.value.title.trim()) {
    return ElMessage.warning('请填写申请单标题')
  }
  submitting.value = true
  try {
    const payload = {
      id: editId.value,
      template_code: selectedTemplateCode.value,
      title: form.value.title,
      action: actionType,
      ref_application_id: form.value.ref_application_id,
      biz_payload: {
        ...form.value.biz_payload,
        budget_limit_cents: Math.round((budgetLimitYuan.value || 0) * 100),
        budget_cents: Math.round((travelBudgetYuan.value || 0) * 100)
      },
      attachment_ids: form.value.attachment_ids,
      procurement_items: form.value.procurement_items.map(i => ({
        item_name: i.item_name,
        specification: i.specification,
        quantity: i.quantity,
        unit: i.unit,
        unit_price_cents: Math.round((i.unit_price_yuan || 0) * 100)
      })),
      procurement_quotes: form.value.procurement_quotes.map((q, idx) => ({
        supplier_name: q.supplier_name,
        quote_date: q.quote_date,
        quoted_amount_cents: Math.round((q.quoted_amount_yuan || 0) * 100),
        purchase_url: q.purchase_url,
        is_selected: idx === selectedQuoteIndex.value,
        attachment_id: q.attachment_id
      })),
      expense_items: form.value.expense_items.map(exp => ({
        expense_type: exp.expense_type,
        occur_date: exp.occur_date,
        description: exp.description,
        amount_cents: Math.round((exp.amount_yuan || 0) * 100),
        is_no_invoice: exp.is_no_invoice,
        no_invoice_reason: exp.no_invoice_reason,
        attachment_ids: exp.attachment_ids
      }))
    }

    const res = await api.post('/applications', payload)
    ElMessage.success(`${res.message}（单号：${res.app_no}）`)
    router.push(`/applications/${res.id}`)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  templates.value = await api.get('/admin/templates')
  linkableApps.value = await api.get('/applications/linkable')

  const qCat = route.query.category
  if (qCat) {
    const matched = templates.value.find(t => t.category === qCat)
    if (matched) selectedTemplateCode.value = matched.code
  }
  onTemplateChange()

  if (editId.value) {
    const detail = await api.get(`/applications/${editId.value}`)
    const tpl = templates.value.find(t => t.id === detail.template_id)
    if (tpl) selectedTemplateCode.value = tpl.code
    form.value.title = detail.title
    form.value.ref_application_id = detail.ref_application_id
    form.value.biz_payload = { ...form.value.biz_payload, ...(detail.biz_payload || {}) }
    budgetLimitYuan.value = (detail.biz_payload?.budget_limit_cents || 600000) / 100
    travelBudgetYuan.value = (detail.biz_payload?.budget_cents || detail.total_amount_cents || 0) / 100
    if (detail.procurement_items?.length) {
      form.value.procurement_items = detail.procurement_items.map(i => ({
        ...i,
        unit_price_yuan: i.unit_price_cents / 100
      }))
    }
    if (detail.procurement_quotes?.length) {
      form.value.procurement_quotes = detail.procurement_quotes.map((q, idx) => {
        if (q.is_selected) selectedQuoteIndex.value = idx
        return { ...q, quoted_amount_yuan: q.quoted_amount_cents / 100 }
      })
    }
    if (detail.expense_items?.length) {
      form.value.expense_items = detail.expense_items.map(e => ({
        ...e,
        amount_yuan: e.amount_cents / 100,
        attachment_ids: detail.attachments.filter(a => a.expense_item_id === e.id).map(a => a.id),
        temp_invoice_no: '',
        dup_warnings: []
      }))
    }
  }
})
</script>

<style scoped>
.sub-section {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 16px;
}
.sub-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.sub-card {
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
}
.submit-bar {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
</style>