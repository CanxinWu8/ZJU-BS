<template>
  <div class="page-card">
    <h3 style="margin: 0 0 14px;">⚙️ 系统管理员控制台（组织权限 · 自定义流程引擎 · 审计留痕）</h3>

    <el-tabs v-model="activeTab">
      <!-- 1. 用户部门确认与角色授权 -->
      <el-tab-pane label="👥 用户与多角色授权" name="users">
        <el-table :data="users" border stripe size="small">
          <el-table-column prop="id" label="ID" width="55" />
          <el-table-column prop="username" label="用户名" width="120" />
          <el-table-column prop="real_name" label="姓名" width="140" />
          <el-table-column prop="department_name" label="所属部门" width="110" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'warning'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="已授予角色">
            <template #default="{ row }">
              <el-tag v-for="r in row.roles" :key="r" size="small" style="margin-right: 4px;">{{ r }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openAuthDialog(row)">授权/变更</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 2. 部门管理 -->
      <el-tab-pane label="🏢 部门架构管理" name="depts">
        <div style="margin-bottom: 12px;">
          <el-button size="small" type="primary" @click="deptDialogVisible = true">+ 新增/更新部门</el-button>
        </div>
        <el-table :data="depts" border size="small">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="code" label="部门编码" width="140" />
          <el-table-column prop="name" label="部门名称" />
          <el-table-column prop="manager_name" label="当前部门负责人" />
        </el-table>
      </el-tab-pane>

      <!-- 3. 自定义审批流程模板引擎 -->
      <el-tab-pane label="🧩 自定义审批流程模板引擎" name="templates">
        <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 13px; color: #64748b;">管理员可在线创建请假、用章、设备借用等任意流程，修改自动递增版本号</span>
          <el-button type="success" @click="openNewTemplateDialog">+ 创建/编辑自定义审批模板</el-button>
        </div>
        <el-table :data="templates" border size="small">
          <el-table-column prop="code" label="模板编码" width="150" />
          <el-table-column prop="name" label="流程名称" />
          <el-table-column prop="category" label="分类" width="110" />
          <el-table-column label="当前版本" width="90">
            <template #default="{ row }">v{{ row.current_version }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用中' : '已停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="editTemplate(row)">升级配置</el-button>
              <el-button size="small" :type="row.is_active ? 'danger' : 'success'" link @click="toggleTpl(row)">
                {{ row.is_active ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 4. 管理与授权变更留痕 -->
      <el-tab-pane label="🛡️ 系统配置与授权审计日志" name="logs">
        <el-table :data="auditLogs" border size="small">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="operator_name" label="操作管理员" width="130" />
          <el-table-column prop="comment" label="变更内容留痕详情" />
          <el-table-column prop="created_at" label="时间" width="175" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 用户授权弹窗 -->
    <el-dialog v-model="authDialogVisible" title="确认用户部门与角色授权" width="480px">
      <el-form :model="authForm" label-width="95px">
        <el-form-item label="所属部门">
          <el-select v-model="authForm.department_id" style="width: 100%;">
            <el-option v-for="d in depts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="账号状态">
          <el-select v-model="authForm.status" style="width: 100%;">
            <el-option label="ACTIVE (正常激活)" value="ACTIVE" />
            <el-option label="PENDING (待确认)" value="PENDING" />
            <el-option label="DISABLED (停用)" value="DISABLED" />
          </el-select>
        </el-form-item>
        <el-form-item label="授予角色">
          <el-checkbox-group v-model="authForm.role_codes">
            <el-checkbox label="EMPLOYEE">普通员工</el-checkbox>
            <el-checkbox label="DEPT_MANAGER">部门负责人</el-checkbox>
            <el-checkbox label="FINANCE">财务审批人</el-checkbox>
            <el-checkbox label="EXECUTIVE">企业负责人</el-checkbox>
            <el-checkbox label="ADMIN">系统管理员</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="authDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUserAuth">保存授权并记录日志</el-button>
      </template>
    </el-dialog>

    <!-- 部门保存弹窗 -->
    <el-dialog v-model="deptDialogVisible" title="新增或更新部门" width="440px">
      <el-form :model="deptForm" label-width="95px">
        <el-form-item label="部门编码">
          <el-input v-model="deptForm.code" placeholder="如 DEPT_HR" />
        </el-form-item>
        <el-form-item label="部门名称">
          <el-input v-model="deptForm.name" placeholder="如 人力资源部" />
        </el-form-item>
        <el-form-item label="部门负责人">
          <el-select v-model="deptForm.manager_user_id" clearable style="width: 100%;">
            <el-option v-for="u in users" :key="u.id" :label="u.real_name" :value="u.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDept">保存部门</el-button>
      </template>
    </el-dialog>

    <!-- 可视化自定义流程模板设计器弹窗 -->
    <el-dialog v-model="tplDialogVisible" title="🧩 可视化自定义审批流程模板设计器" width="760px">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :xs="24" :sm="8">
            <el-form-item label="模板唯一编码" required>
              <el-input v-model="tplForm.code" placeholder="如 CUSTOM_DEVICE" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="10">
            <el-form-item label="流程模板名称" required>
              <el-input v-model="tplForm.name" placeholder="如 研发设备借用审批" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="6">
            <el-form-item label="流程分类">
              <el-select v-model="tplForm.category" style="width: 100%;">
                <el-option label="自定义流程 (CUSTOM)" value="CUSTOM" />
                <el-option label="采购审批" value="PROCUREMENT" />
                <el-option label="差旅申请" value="TRAVEL" />
                <el-option label="报销审批" value="EXPENSE" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 动态表单字段编排 -->
        <div style="margin-bottom: 14px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <b>1. 表单字段配置（支持单行/多行/数字/日期/单选/附件）</b>
            <el-button size="small" type="primary" plain @click="addTplField">+ 添加字段</el-button>
          </div>
          <div v-for="(f, idx) in tplForm.fields" :key="idx" style="display: flex; gap: 6px; margin-bottom: 6px; flex-wrap: wrap;">
            <el-input v-model="f.field_key" placeholder="标识key" style="width: 120px;" size="small" />
            <el-input v-model="f.label" placeholder="显示名称" style="width: 130px;" size="small" />
            <el-select v-model="f.type" style="width: 110px;" size="small">
              <el-option label="单行文本" value="text" />
              <el-option label="多行文本" value="textarea" />
              <el-option label="数字/金额" value="number" />
              <el-option label="日期" value="date" />
              <el-option label="单选" value="radio" />
              <el-option label="附件" value="file" />
            </el-select>
            <el-input v-if="f.type === 'radio'" v-model="f.options_str" placeholder="逗号分隔选项: 公章,财务章" style="width: 180px;" size="small" />
            <el-checkbox v-model="f.required" size="small">必填</el-checkbox>
            <el-button v-if="tplForm.fields.length > 1" size="small" type="danger" link @click="tplForm.fields.splice(idx, 1)">删</el-button>
          </div>
        </div>

        <!-- 顺序审批节点配置（支持上移/下移调整顺序，至少2个节点） -->
        <div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <b>2. 顺序审批节点配置（不少于 2 个节点，可调整顺序）</b>
            <el-button size="small" type="success" plain @click="addTplNode">+ 添加审批节点</el-button>
          </div>
          <div v-for="(n, idx) in tplForm.nodes_config" :key="idx" style="display: flex; gap: 6px; align-items: center; margin-bottom: 8px; flex-wrap: wrap;">
            <el-tag size="small">节点 {{ idx + 1 }}</el-tag>
            <el-input v-model="n.node_name" placeholder="节点名称" style="width: 150px;" size="small" />
            <el-select v-model="n.rule_type" style="width: 150px;" size="small">
              <el-option label="申请人部门负责人" value="DEPT_MANAGER" />
              <el-option label="按角色解析" value="ROLE" />
              <el-option label="指定具体用户" value="USER" />
            </el-select>
            <el-select v-if="n.rule_type === 'ROLE'" v-model="n.rule_value" style="width: 130px;" size="small" placeholder="选择角色">
              <el-option label="财务审批人" value="FINANCE" />
              <el-option label="企业负责人" value="EXECUTIVE" />
            </el-select>
            <el-select v-if="n.rule_type === 'USER'" v-model="n.rule_value" style="width: 130px;" size="small" placeholder="选择用户">
              <el-option v-for="u in users" :key="u.id" :label="u.real_name" :value="u.id" />
            </el-select>
            <el-button size="small" :disabled="idx === 0" @click="moveNode(idx, -1)">↑上移</el-button>
            <el-button size="small" :disabled="idx === tplForm.nodes_config.length - 1" @click="moveNode(idx, 1)">↓下移</el-button>
            <el-button v-if="tplForm.nodes_config.length > 2" size="small" type="danger" link @click="tplForm.nodes_config.splice(idx, 1)">删</el-button>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="tplDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="publishTemplate">校验并发布新版本</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const activeTab = ref('users')
const users = ref([])
const depts = ref([])
const templates = ref([])
const auditLogs = ref([])

const authDialogVisible = ref(false)
const editingUserId = ref(null)
const authForm = ref({ department_id: 1, status: 'ACTIVE', role_codes: ['EMPLOYEE'] })

const deptDialogVisible = ref(false)
const deptForm = ref({ code: '', name: '', manager_user_id: null })

const tplDialogVisible = ref(false)
const tplForm = ref({
  code: 'CUSTOM_DEVICE',
  name: '研发设备借用审批',
  category: 'CUSTOM',
  description: '实验室测试机与高价值仪器借用申请',
  fields: [
    { field_key: 'device_name', label: '借用设备名称', type: 'text', required: true, options_str: '' },
    { field_key: 'borrow_days', label: '借用天数', type: 'number', required: true, options_str: '' },
    { field_key: 'return_date', label: '预计归还日期', type: 'date', required: true, options_str: '' },
    { field_key: 'purpose', label: '借用用途说明', type: 'textarea', required: true, options_str: '' }
  ],
  nodes_config: [
    { node_name: '申请人部门负责人审批', rule_type: 'DEPT_MANAGER', rule_value: null, min_amount_cents: 0 },
    { node_name: '企业负责人终审', rule_type: 'ROLE', rule_value: 'EXECUTIVE', min_amount_cents: 0 }
  ]
})

async function loadAll() {
  users.value = await api.get('/admin/users')
  depts.value = await api.get('/admin/departments')
  templates.value = await api.get('/admin/templates?include_inactive=true')
  auditLogs.value = await api.get('/admin/audit-logs')
}

function openAuthDialog(u) {
  editingUserId.value = u.id
  authForm.value = {
    department_id: u.department_id,
    status: u.status,
    role_codes: [...u.roles]
  }
  authDialogVisible.value = true
}

async function saveUserAuth() {
  const res = await api.put(`/admin/users/${editingUserId.value}/authorize`, authForm.value)
  ElMessage.success(res.message)
  authDialogVisible.value = false
  loadAll()
}

async function saveDept() {
  const res = await api.post('/admin/departments', deptForm.value)
  ElMessage.success(res.message)
  deptDialogVisible.value = false
  loadAll()
}

function openNewTemplateDialog() {
  tplDialogVisible.value = true
}

function editTemplate(row) {
  tplForm.value = {
    code: row.code,
    name: row.name,
    category: row.category,
    description: row.description,
    fields: (row.form_schema?.fields || []).map(f => ({
      ...f,
      options_str: (f.options || []).join(',')
    })),
    nodes_config: (row.nodes_config || []).map(n => ({ ...n }))
  }
  tplDialogVisible.value = true
}

function addTplField() {
  tplForm.value.fields.push({ field_key: '', label: '', type: 'text', required: true, options_str: '' })
}

function addTplNode() {
  tplForm.value.nodes_config.push({ node_name: '新增审批节点', rule_type: 'DEPT_MANAGER', rule_value: null, min_amount_cents: 0 })
}

function moveNode(idx, dir) {
  const arr = tplForm.value.nodes_config
  const target = idx + dir
  const temp = arr[idx]
  arr[idx] = arr[target]
  arr[target] = temp
}

async function publishTemplate() {
  const payload = {
    code: tplForm.value.code,
    name: tplForm.value.name,
    category: tplForm.value.category,
    description: tplForm.value.description,
    fields: tplForm.value.fields.map(f => ({
      field_key: f.field_key,
      label: f.label,
      type: f.type,
      required: f.required,
      options: f.type === 'radio' ? (f.options_str || '').split(',').map(s => s.trim()).filter(Boolean) : null
    })),
    nodes_config: tplForm.value.nodes_config.map((n, i) => ({
      node_seq: i + 1,
      node_name: n.node_name,
      rule_type: n.rule_type,
      rule_value: n.rule_value,
      min_amount_cents: n.min_amount_cents || 0
    }))
  }
  const res = await api.post('/admin/templates', payload)
  ElMessage.success(res.message)
  tplDialogVisible.value = false
  loadAll()
}

async function toggleTpl(row) {
  const nextStatus = row.is_active ? 0 : 1
  const res = await api.patch(`/admin/templates/${row.id}/status?is_active=${nextStatus}`)
  ElMessage.success(res.message)
  loadAll()
}

onMounted(loadAll)
</script>