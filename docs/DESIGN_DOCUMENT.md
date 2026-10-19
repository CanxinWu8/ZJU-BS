# 设计文档

## 1. 引言与需求分析

### 1.1 编写目的与项目背景

本项目旨在设计并独立实现一套基于 B/S 架构的企业审批 Web 应用系统。系统覆盖企业日常核心业务流转，包括**采购审批**、**差旅申请**、**报销审批**以及**系统管理员可自主定义的扩展审批流程**（如请假、用章、设备借用等）。系统通过多部门组织架构与细粒度基于角色的访问控制（RBAC + 数据范围控制），实现从申请草稿保存、表单校验提交、多级顺序流转、快照留痕、附件安全鉴权、查询统计到实时进度提醒的全生命周期闭环管理。

### 1.2 功能范围矩阵

根据课程实验要求，本系统的功能规划划分为“基础必做”、“重点提分”与“精选增强”三个层次：

|**模块层级**|**包含子模块 / 功能特性**|**验收关键指标**|
|---|---|---|
|**基础必做**|**1. 通用界面与工作台**：注册/登录/退出、个人信息、我的申请/待办/已办、通知中心、管理员后台<br><br>  <br><br>**2. 组织与多维权限**：研发/市场/财务等部门；普通员工、部门负责人、财务审批人、企业负责人、系统管理员五类角色<br><br>  <br><br>**3. 三大固定业务审批**：采购审批（含多明细与供应商比价）、差旅申请（含自然日计算与后续关联）、报销审批（含分项明细、票据防重与无票例外高亮）<br><br>  <br><br>**4. 管理员自定义流程引擎**：可视化配置动态表单字段与校验规则、配置多级审批节点与人员解析规则、版本管理<br><br>  <br><br>**5. 审批流转、统计与站内信**：状态机流转、快照防篡改、并发乐观锁、ECharts 图表统计、持久化站内通知<br><br>  <br><br>**6. 容器化部署**：数据库持久化、可重复执行的迁移与种子脚本、`docker-compose` 一键启动|服务端强权限校验、金额采用整数“分”精确计算、提交即生成流程与人员快照、全操作审计留痕。|
|**重点提分**|**1. 移动端响应式与触控适配**：基于 PWA + 响应式移动端视图，表格自动降级为卡片/分步表单，支持手机拍照直传票据<br><br>  <br><br>**2. 实时与后台进度提醒**：基于 SSE（Server-Sent Events）实现在线免刷新实时弹窗提醒；结合 **Web Push API + 邮件通知（SMTP）** 实现页面关闭/后台状态下的触达提醒|手机端无横向滚动完成全部核心操作；后台推送失败或拒权时自动降级保留站内通知。|
|**可选增强**|**1. 跨申请重复票据智能预警**：基于票据号码 + 文件 SHA-256 哈希双维度检测跨单重复报销，在财务审核端高亮告警<br><br>  <br><br>**2. 审批委托与一键催办**：支持审批人设置时间段内的代理人自动转交待办；申请人可对超时未处理节点发起防刷催办<br><br>  <br><br>**3. 可视化流程设计器**：基于流程图节点拖拽/连线配置审批路径|具备完整的前后端交互逻辑与审计日志记录，提供清晰可验证的演示证据。|

## 2. 系统总体架构设计

### 2.1 技术栈选型

为兼顾开发效率、类型安全、移动端兼容与容器化部署便利性，本系统采用前后端分离的现代化 B/S 架构：

- **前端技术栈**：
    
    - **核心框架**：Vue 3 (Composition API) + TypeScript + Vite
        
    - **UI 组件库**：桌面端采用 Element Plus，移动端自适应视图结合 Vant 4 / Tailwind CSS（实现桌面端表格与移动端卡片流无缝切换）
        
    - **状态管理与路由**：Pinia + Vue Router 4（配合动态路由守卫）
        
    - **数据可视化与流程图**：Apache ECharts（统计报表）+ LogicFlow / Vue Flow（自定义流程可视化编排）
        
    - **移动端与推送**：Vite PWA Plugin + Web Push Service Worker + EventSource (SSE)
        
- **后端技术栈**：
    
    - **核心框架**：Python FastAPI（异步高性能、原生支持 OpenAPI/Swagger 自动文档与 Pydantic 强类型数据校验） _(注：亦可无缝替换为 Spring Boot 3，本文档接口与数据库设计完全通用)_
        
    - **ORM 与数据迁移**：SQLAlchemy 2.0 + Alembic（提供版本化 schema 迁移与幂等初始化数据脚本）
        
    - **安全与认证**：JWT (Access Token + Refresh Token) + Passlib (BCrypt 密码哈希，强制 $\ge 8$ 位)
        
- **数据存储与基础设施**：
    
    - **关系型数据库**：MySQL 8.0（事务隔离、行级锁与 JSON 字段原生支持）
        
    - **附件存储**：本地持久化数据卷（Docker Volume 映射，通过后端受保护的流式接口鉴权后预览/下载，严禁 Nginx 直接暴露静态文件目录）
        
    - **部署运维**：Docker + Docker Compose（包含 `frontend-nginx`、`backend-api`、`mysql-db` 三个容器服务）
        

### 2.2 系统拓扑与分层架构图

```Code snippet
graph TB
    subgraph Client ["客户端层 (Browser / Mobile PWA)"]
        PC["桌面端浏览器<br/>(Element Plus + ECharts)"]
        Mobile["移动端浏览器 / PWA应用<br/>(触控卡片视图 + 相机直传)"]
        SW["Service Worker<br/>(Web Push 后台推送监听)"]
    end

    subgraph Gateway ["网关与反向代理层 (Docker Container)"]
        Nginx["Nginx Web Server<br/>(静态资源托管 / API反向代理 / HTTPS)"]
    end

    subgraph Backend ["服务端应用层 (FastAPI / Spring Boot)"]
        AuthMW["安全认证与RBAC权限拦截器<br/>(JWT校验 / 资源级Data Scope检查)"]
        
        subgraph Controllers ["业务控制器层 (RESTful APIs)"]
            UserAPI["用户与组织管理"]
            BizAPI["三大固定业务与自定义申请"]
            EngineAPI["工作流流转与快照引擎"]
            FileAPI["受控附件上传/鉴权预览"]
            StatAPI["统计报表与通知中心"]
        end

        subgraph Services ["核心领域服务层"]
            FlowEngine["状态机与并发控制服务<br/>(乐观锁 / 节点解析 / 代理委托)"]
            FormValidator["动态表单Schema校验器"]
            InvoiceCheck["票据SHA-256与票号查重引擎"]
            NotifySvc["多通道通知分发服务<br/>(站内信 + SSE + WebPush + SMTP)"]
        end
    end

    subgraph Storage ["数据持久化层 (Docker Volumes)"]
        MySQL[("MySQL 8.0 数据库<br/>(业务表 / 快照JSON / 审计日志)")]
        FileVol[("受控文件存储卷<br/>(采购截图 / 报销PDF与图片)")]
    end

    PC & Mobile -->|HTTPS / REST API| Nginx
    PC & Mobile -.->|SSE 实时流| Nginx
    SW -.->|Web Push 后台唤醒| NotifySvc
    Nginx --> AuthMW
    AuthMW --> Controllers
    Controllers --> Services
    Services --> MySQL
    FileAPI --> FileVol
```

## 3. 安全与多维权限控制设计

根据实验要求，系统**严禁仅通过前端隐藏按钮实现权限控制**，所有列表查询、详情读取、审批动作、附件预览下载及统计接口均在服务端执行双重校验（功能角色校验 + 数据范围 Data Scope 校验）。

### 3.1 部门与角色模型设计

- **预设部门**：研发部 (`DEPT_RND`)、市场部 (`DEPT_MKT`)、财务部 (`DEPT_FIN`)、总经办 (`DEPT_EXEC`)，支持管理员动态增改。
    
- **用户状态流转**：新用户注册时需填写用户名（唯一）、姓名、邮箱（唯一）、密码（$\ge 8$ 位，BCrypt 哈希存储）及申请加入的部门。注册后默认状态为 `PENDING`（待确认）或仅具 `EMPLOYEE` 基础身份，**客户端注册/修改接口严禁接收 `roles`、`is_admin` 等提权字段**，部门确认及高权限角色授予必须由系统管理员在后台完成并记录审计日志。
    
- **多角色兼任**：通过 `user_roles` 关联表支持一人兼任多角（例如：财务部负责人同时具备“部门负责人”和“财务审批人”角色），每个角色可绑定作用部门范围（本部门 `SELF_DEPT` 或全公司 `ALL`）。
    

### 3.2 服务端接口级数据范围（Data Scope）矩阵

|**角色标识**|**角色名称**|**核心操作权限**|**服务端数据访问范围（Data Scope）强制过滤规则**|
|---|---|---|---|
|`EMPLOYEE`|普通员工|提交/保存/撤回本人申请、上传附件、复制重提|仅限 `applicant_id == current_user.id` 的申请单及对应附件；**严禁审批本人申请** (`approver_id != applicant_id`)。|
|`DEPT_MANAGER`|部门负责人|审批本部门待办、查看本部门审批统计|审批接口校验 `current_node.approver_id == current_user.id`；统计与查询接口强制过滤 `department_id == current_user.dept_id`，禁止跨部门遍历。|
|`FINANCE`|财务审批人|处理预算审查、报销审核、查看授权财务统计|仅可访问当前/历史审批链路中包含本人（或本角色已解析到本人）的申请单及财务统计，不因财务身份自动透视全公司未授权的日常行政申请。|
|`EXECUTIVE`|企业负责人|审批大额采购/大额报销/特定流程、企业级统计|访问分配给本人的高金额或特定节点申请；仅在显式授予 `SCOPE_COMPANY_STAT` 权限标记时可查看全公司汇总统计。|
|`ADMIN`|系统管理员|管理部门、用户确认、角色授权、配置流程模板|**管理权与业务审批/查看权严格分离**。管理员默认不可直接调阅员工申请正文与报销隐私票据；若需排查问题，必须通过“临时审计授权”功能申请并强制写入不可篡改的《系统管理与隐私访问审计日志》。|

### 3.3 附件安全防越权机制

所有上传的报价单、电子发票（JPEG/PNG/PDF）均重命名为 UUID 存储于非公开目录，并在数据库 `attachments` 表中绑定 `application_id` 与文件 SHA-256 值。 当用户请求 `/api/v1/attachments/{file_id}/preview` 或 `/download` 时，服务端执行以下鉴权链：

1. 验证 JWT 登录态；
    
2. 查询该附件归属的 `application_id`；
    
3. 检查当前用户是否为以下合法访问者之一：**该申请的提交人本人**、**该申请审批实例中的历史/当前审批人**、或**已获显式授权的财务/企业审计员**。校验通过后，由后端通过 `FileResponse` / `StreamingResponse` 输出文件流。
    

## 4. 核心业务模块详细设计

### 4.1 金额精度与通用编号规则

- **金额无损精度设计**：为彻底规避 IEEE 754 浮点数精度误差（如 `0.1 + 0.2 != 0.3`）导致审批条件分支误判，系统在数据库层与后端计算层**统一采用 64 位整数 `BIGINT` 存储金额，单位为“分”（Cent）**（例如 `199.99` 元存储为 `19999`）。前端展示时格式化为两位小数，服务端接收请求时强制重新汇总所有明细行金额，**绝不信任前端传入的 `total_amount` 字段**。
    
- **全局唯一申请编号**：服务端按规则自动生成，格式为 `{业务前缀}-{YYYYMMDD}-{6位每日自增序列或随机唯一码}`（如采购 `PUR-20261116-000042`、差旅 `TRV-20261116-000015`、报销 `EXP-20261116-000089`、自定义 `CUS-20261116-000003`），并在数据库建立 `UNIQUE` 唯一索引。
    

### 4.2 采购审批模块（Procurement）

1. **数据结构**：采用“主表扩展 + 多条采购明细表 (`procurement_items`) + 供应商报价表 (`procurement_quotes`)”结构。
    
2. **业务校验规则**：
    
    - 采购明细行必须 $\ge 2$ 条（实验要求支持至少两条明细增删），每条明细包含：名称、规格、数量（$>0$）、单位、预计单价（分），服务端自动计算行小计 `subtotal = quantity * unit_price` 及整单预算总额。
        
    - **比价强制校验**：默认要求录入至少 **2 家**供应商报价（含供应商名称、报价日期、报价总额、报价依据附件/电商链接与截图）。
        
    - **单一来源例外机制**：若开启 `is_single_source = true`（单一来源采购），允许仅提供 1 家供应商，但必须填写 `single_source_reason`（不少于 15 字），且在审批详情页顶部以醒目黄色警告横幅提示审批人。
        
    - **非最低价说明强制校验**：服务端自动比对所有录入供应商的报价金额。若申请人选择的拟定供应商（`selected_quote_id`）报价高于最低报价，服务端强制校验 `non_lowest_reason`（未选最低价理由）字段非空，否则拒绝提交。
        

### 4.3 差旅申请模块（Business Travel）

1. **表单要素**：出发地、目的地、开始时间 (`start_time`)、结束时间 (`end_time`)、出差目的、同行人员（支持选择系统内员工 ID 数组或补充外部人员文本）、交通工具（高铁/飞机/自驾/其他）、预算金额（分，必须 $\ge 0$）、补充说明及附件。
    
2. **时间口径与自动计算**：
    
    - 服务端强制校验 `end_time >= start_time`。
        
    - **出差天数计算口径（在界面与接口中明确标注）**：采用**自然日口径**计算，公式为：
        $$\text{duration\_days} = (\text{Date}(\text{end\_time}) - \text{Date}(\text{start\_time})).\text{days} + 1$$
        同时辅以精确小时数展示，避免跨日歧义。
        
3. **跨单闭环关联**：差旅申请状态流转为 `APPROVED`（已通过）后，会自动进入该申请人名下的“可关联前置申请池”，供后续提交报销单时下拉绑定，并在报销审批界面直接联动展示原差旅单的地点、时间与批准预算对比。
    

### 4.4 报销审批模块（Expense Reimbursement）与票据防重

1. **表单与关联**：支持选择本人已批准的“差旅申请”或“采购申请”进行关联，也支持勾选“独立日常报销”并填写说明。
    
2. **费用明细与分类**：支持动态增删修改明细行（实验演示支持 $\ge 3$ 条明细），预设费用类型字典：`TRAFFIC`（交通）、`HOTEL`（住宿）、`MEAL`（餐饮）、`OFFICE`（办公）、`OTHER`（其他），管理员可在后台维护字典。
    
3. **票据强约束与无票例外高亮**：
    
    - 每条费用明细金额必须 $> 0$。
        
    - 默认每条明细必须上传至少 1 份票据文件（支持 JPEG/PNG/PDF，单文件 $\le 10\text{MB}$，单张报销单总附件 $\le 20$ 个且总大小 $\le 50\text{MB}$）。
        
    - **无票支出例外**：若某明细勾选 `is_no_invoice = true`，则必须填写 `no_invoice_reason`（无票原因）。在财务审批人界面，该行明细将以红色高亮标签（“无票异常支出”）置顶提示，防止静默跳过。
        
4. **同单防重与跨单重复报销预警（增强亮点）**：
    
    - **同单绝对阻断**：同一张报销单的不同明细行之间，严禁绑定同一个 `attachment_id`、相同文件 SHA-256 哈希或相同的 `invoice_no`（发票号码），服务端直接报错阻断提交。
        
    - **跨单智能预警（增强功能）**：每次上传票据或填写发票号时，服务端自动计算文件二进制流的 `SHA-256` 摘要，并在全局历史报销库（含 `PENDING` 和 `APPROVED` 状态）中检索是否存在相同的 `invoice_no` 或相同的 `file_sha256`。若命中，系统生成一条 `DUPLICATE_INVOICE_WARNING` 风险记录，在审批页向部门负责人与财务审批人展示撞单详情（原报销单号、提交人、提交时间），辅助财务精准拦截重复报销。
        

### 4.5 管理员自定义审批流程引擎（Custom Workflow Engine）

为彻底杜绝“硬编码改代码或复制页面”应付检查，系统设计了数据驱动的 **JSON Schema 动态表单渲染器 + 流程模板版本化引擎**：

1. **流程模板定义 (`workflow_templates` & `workflow_template_versions`)**：
    
    - 包含模板名称（如“印章使用申请”、“员工请假申请”、“研发设备借用”）、说明、适用部门范围、当前版本号 `version`、启用状态 `is_active`。
        
    - **版本隔离机制**：管理员每次修改已发布模板的表单字段或节点配置并保存发布时，系统自动递增生成新版本 `v2, v3...`；历史已提交的申请单永久绑定提交当时的 `template_version_id` 与快照，不受后续修改影响。
        
2. **动态表单配置 (`form_schema`)**：
    
    - 支持配置字段类型：`text`（单行文本）、`textarea`（多行文本）、`number`（数字/金额）、`date`（日期）、`radio`（单选下拉）、`file`（附件上传）。
        
    - 每个字段包含属性：`field_key`（唯一标识）、`label`（显示名称）、`required`（是否必填）、`rules`（正则、最小值、最大值、条件显隐）。
        
3. **多级顺序审批节点配置 (`nodes_config`)**：
    
    - 支持可视化拖拽调整顺序（不少于 2 个节点），并支持设置**条件分支阈值**（如：`amount > 500000` 即金额超 5000 元时激活企业负责人节点）。
        
    - 审批人解析规则（Approver Resolution）支持三类：
        
        1. `APPLICANT_DEPT_MANAGER`：自动解析为申请人所在部门的当前负责人；
            
        2. `ROLE_HOLDER`：解析为特定角色持有者（如财务审批人、企业负责人）；
            
        3. `SPECIFIC_USER`：指定具体的某个系统用户 ID。
            
4. **发布前静态完整性校验（Pre-publish Validation）**：
    
    - 校验所有 `field_key` 唯一且非空；
        
    - 校验条件表达式引用的字段存在于 `form_schema` 中且类型匹配；
        
    - 校验节点数量 $\ge 2$，各节点审批人规则当前均可解析出至少一名有效在职用户，且节点依赖图无环（DAG 拓扑检测）。
        

## 5. 审批流转引擎、状态机与并发控制设计

### 5.1 申请单全生命周期状态机

Code snippet

```
stateDiagram-v2
    [*] --> DRAFT : 创建并保存草稿
    [*] --> IN_REVIEW : 直接校验并提交
    
    DRAFT --> DRAFT : 申请人编辑修改
    DRAFT --> DELETED : 申请人删除草稿
    DRAFT --> IN_REVIEW : 校验通过并提交(生成路径与人员快照)
    
    IN_REVIEW --> IN_REVIEW : 当前节点审批通过(进入下一顺序节点)
    IN_REVIEW --> APPROVED : 最后一个节点审批通过
    IN_REVIEW --> REJECTED : 当前审批人驳回(必填理由)
    IN_REVIEW --> WITHDRAWN : 申请人在终审前主动撤回
    
    REJECTED --> DRAFT : 申请人一键复制生成新版本/新申请(关联原单ID)
    WITHDRAWN --> DRAFT : 申请人一键复制生成新版本/新申请(关联原单ID)
    
    APPROVED --> [*]
    DELETED --> [*]
```

### 5.2 提交时快照机制（Snapshot Mechanism）

实验明确要求：“申请均在提交时保存本次审批路径、规则口径和人员快照，后续阈值或人员配置变化不得自动改写已有实例”。 本系统在用户点击“提交申请”的数据库事务中执行以下固化操作：

1. 读取当前匹配的流程模板版本及金额阈值规则，计算本次申请需经过的完整节点序列。
    
2. 将每个节点的抽象规则（如“申请人部门负责人”）**立即解析为具体的用户 ID (`resolved_approver_id`) 及用户姓名快照**。若该审批人当前配置了生效中的“审批委托规则”（增强功能），则自动解析为代理人并记录原审批人信息。
    
3. **自我审批规避校验**：若某节点解析出的审批人恰好是申请人本人（例如部门负责人自己提交申请），系统根据预设策略自动上浮至企业负责人或报错提示由管理员指定，严格保证 `approver_id != applicant_id`。
    
4. 将完整的表单 Schema、规则口径及节点序列写入 `approval_instance_nodes` 实例表及主表的 `snapshot_json` 字段中。第一个节点状态设为 `PENDING`（激活待办），其余后续节点设为 `WAITING`（未到达，严禁越级提前审批）。
    

### 5.3 并发控制与幂等性保障（防重复点击 / 撤回与审批竞争）

在“两个浏览器同时点击审批”、“网络重试”或“申请人撤回与审批人点击通过同时发生”的高并发场景下，系统采用**数据库行级排他锁 (`SELECT ... FOR UPDATE`) + 乐观锁版本号 (`version`)** 双重机制确保强一致性：

SQL

```
-- 审批或撤回状态变更时的原子更新 SQL 逻辑
UPDATE applications 
SET status = :new_status, 
    current_node_seq = :next_seq, 
    version = version + 1, 
    updated_at = NOW()
WHERE id = :app_id 
  AND status = 'IN_REVIEW' 
  AND version = :expected_version;
```

- 若受影响行数 `affected_rows == 0`，说明该申请已被另一并发请求（如申请人刚刚完成了撤回，或另一窗口已完成审批）抢先修改了状态和 `version`。
    
- 此时当前事务立即回滚，并向前端返回 `HTTP 409 Conflict` 及明确提示：_“当前申请状态或待办节点已发生变化，请刷新页面后查看最新进度”_，从而保证**绝不产生两次有效流转、绝不发送重复通知、待办状态与审批日志 100% 一致**。
    

### 5.4 核心审批流转与并发控制时序图

```Code
sequenceDiagram
    autonumber
    actor Emp as 申请人 (普通员工)
    actor Mgr as 当前审批人 (部门负责人)
    participant API as 后端服务 (Workflow Engine)
    participant DB as MySQL 数据库
    participant Notify as 通知中心 (站内信/SSE/WebPush)

    Emp->>API: POST /api/v1/applications (提交申请)
    activate API
    API->>API: 1. 校验表单字段、重算整数(分)总额、票据SHA256查重
    API->>DB: 2. 开启事务，解析当前审批人快照，生成申请单(version=1)与节点序列
    API->>DB: 3. 写入提交审计日志 (action=SUBMIT) + 唯一通知记录(幂等Key)
    DB-->>API: 事务提交成功
    API->>Notify: 4. 异步推送新待办提醒 (SSE实时流 + WebPush)
    API-->>Emp: 201 Created (返回唯一申请单号)
    deactivate API

    par 并发竞争场景演示：审批人点击批准 vs 申请人点击撤回
        Mgr->>API: POST /api/v1/applications/{id}/approve (携带 version=1)
        Emp->>API: POST /api/v1/applications/{id}/withdraw (携带 version=1)
    end

    activate API
    Note over API,DB: 审批请求率先获得行锁并更新 version = 2
    API->>DB: UPDATE applications SET version=2 ... WHERE id={id} AND version=1
    DB-->>API: affected_rows = 1 (更新成功，推进至下一节点或APPROVED)
    API->>DB: 更新当前待办为APPROVED，激活下一节点，写入审批日志
    API->>Notify: 触发状态变更通知 (幂等键: app_{id}_v2_approve)
    API-->>Mgr: 200 OK (审批通过)

    Note over API,DB: 紧随其后的撤回请求执行更新时 version=1 条件不满足
    API->>DB: UPDATE applications SET status='WITHDRAWN', version=2 WHERE id={id} AND version=1
    DB-->>API: affected_rows = 0 (乐观锁冲突拦截)
    API-->>Emp: 409 Conflict ("操作失败：该申请已被审批人处理，无法撤回")
    deactivate API
```

## 6. 数据库详细设计

本系统使用 **MySQL 8.0** 作为持久化存储引擎（字符集 `utf8mb4`）。以下设计完整覆盖实验要求的 10 类核心实体，并明确定义外键关联与删除策略。

### 6.1 实体关系图（E-R 图）

```Code snippet
erDiagram
    DEPARTMENTS ||--o{ USERS : "归属部门(RESTRICT)"
    USERS ||--o{ USER_ROLES : "拥有角色(CASCADE)"
    ROLES ||--o{ USER_ROLES : "分配给(CASCADE)"
    
    WORKFLOW_TEMPLATES ||--|{ WORKFLOW_TEMPLATE_VERSIONS : "包含版本(RESTRICT)"
    WORKFLOW_TEMPLATE_VERSIONS ||--o{ APPLICATIONS : "实例化自(RESTRICT)"
    
    USERS ||--o{ APPLICATIONS : "提交申请(RESTRICT)"
    DEPARTMENTS ||--o{ APPLICATIONS : "归属部门快照(RESTRICT)"
    APPLICATIONS ||--o| APPLICATIONS : "重提关联原单(SET NULL)"
    APPLICATIONS ||--o| APPLICATIONS : "报销关联差旅/采购(RESTRICT)"
    
    APPLICATIONS ||--o{ PROCUREMENT_ITEMS : "采购明细(CASCADE)"
    APPLICATIONS ||--o{ PROCUREMENT_QUOTES : "供应商比价(CASCADE)"
    APPLICATIONS ||--o{ EXPENSE_ITEMS : "报销费用明细(CASCADE)"
    
    APPLICATIONS ||--|{ APPROVAL_INSTANCE_NODES : "流转节点快照(CASCADE)"
    APPLICATIONS ||--|{ APPROVAL_LOGS : "不可篡改审批日志(RESTRICT)"
    APPLICATIONS ||--o{ ATTACHMENTS : "业务与票据附件(CASCADE)"
    
    USERS ||--o{ NOTIFICATIONS : "接收通知(CASCADE)"
    USERS ||--o{ APPROVAL_DELEGATIONS : "委托代理(CASCADE)"
```

### 6.2 关联与删除策略说明（Deletion & Integrity Policy）

1. **严禁物理删除已提交业务数据**：`applications`（非草稿状态）、`approval_logs`、`workflow_template_versions`、`users`、`departments` 均采用逻辑停用（软删除 `is_deleted` / `status = DISABLED`）配合外键 `ON DELETE RESTRICT` 策略。即使某员工离职或某流程模板停用，历史审批单据、人员快照与审批日志依然永久完整可查。
    
2. **草稿级联清理**：仅当申请单处于 `DRAFT`（草稿）状态且申请人主动点击删除时，允许通过事务级联清理其关联的明细行与未绑定的临时附件 (`ON DELETE CASCADE`)。
    
3. **审批日志只增不改（Append-Only）**：`approval_logs` 与 `admin_audit_logs` 表在应用层不提供任何 `UPDATE` 或 `DELETE` DAO 方法，确保操作留痕的法律与审计效力。
    

### 6.3 核心表结构定义（DDL 摘要）

_(完整的建表脚本与初始化种子数据将置于项目仓库 `db/init.sql` 与 Alembic 迁移脚本中，随 Docker 启动自动幂等执行)_

```SQL
-- 1. 部门表 (departments)
CREATE TABLE departments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(32) NOT NULL UNIQUE COMMENT '部门编码: DEPT_RND, DEPT_MKT, DEPT_FIN, DEPT_EXEC',
    name VARCHAR(64) NOT NULL COMMENT '部门名称',
    manager_user_id BIGINT NULL COMMENT '当前部门负责人ID',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 用户表 (users)
CREATE TABLE users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL UNIQUE COMMENT '唯一登录用户名',
    real_name VARCHAR(64) NOT NULL COMMENT '真实姓名',
    email VARCHAR(128) NOT NULL UNIQUE COMMENT '唯一邮箱(兼用于邮件提醒)',
    password_hash VARCHAR(255) NOT NULL COMMENT 'BCrypt加密哈希(密码>=8位)',
    department_id BIGINT NOT NULL COMMENT '所属部门ID',
    status ENUM('PENDING', 'ACTIVE', 'DISABLED') NOT NULL DEFAULT 'PENDING' COMMENT '注册默认待确认或普通员工',
    webpush_sub_json JSON NULL COMMENT 'WebPush浏览器推送订阅凭证',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_dept FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 角色与用户角色映射表 (roles & user_roles)
CREATE TABLE roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(32) NOT NULL UNIQUE COMMENT 'EMPLOYEE, DEPT_MANAGER, FINANCE, EXECUTIVE, ADMIN',
    name VARCHAR(64) NOT NULL,
    default_data_scope ENUM('SELF', 'DEPT', 'AUTHORIZED_BIZ', 'COMPANY') NOT NULL DEFAULT 'SELF'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE user_roles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    managed_dept_id BIGINT NULL COMMENT '当兼任特定部门负责人时绑定的部门ID',
    granted_by BIGINT NULL COMMENT '授权管理员ID',
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_role_dept (user_id, role_id, managed_dept_id),
    CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 流程模板与版本表 (workflow_templates & workflow_template_versions)
CREATE TABLE workflow_templates (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(64) NOT NULL UNIQUE COMMENT '模板唯一编码: PROCURE, TRAVEL, EXPENSE 或自定义编码',
    name VARCHAR(128) NOT NULL COMMENT '流程名称',
    category ENUM('PROCUREMENT', 'TRAVEL', 'EXPENSE', 'CUSTOM') NOT NULL,
    description VARCHAR(500) NULL,
    applicable_dept_ids JSON NULL COMMENT '适用部门ID列表，NULL表示全公司适用',
    current_version INT NOT NULL DEFAULT 1,
    is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '启用/停用状态',
    created_by BIGINT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE workflow_template_versions (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_id BIGINT NOT NULL,
    version_num INT NOT NULL COMMENT '版本号 1, 2, 3...',
    form_schema JSON NOT NULL COMMENT '动态表单字段定义与校验规则(JSON Schema)',
    nodes_config JSON NOT NULL COMMENT '顺序审批节点、条件阈值及审批人解析规则',
    published_by BIGINT NOT NULL,
    published_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_tpl_ver (template_id, version_num),
    CONSTRAINT fk_ver_tpl FOREIGN KEY (template_id) REFERENCES workflow_templates(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 申请主表 (applications)
CREATE TABLE applications (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    app_no VARCHAR(40) NOT NULL UNIQUE COMMENT '系统生成唯一编号 如 PUR-20261116-000001',
    category ENUM('PROCUREMENT', 'TRAVEL', 'EXPENSE', 'CUSTOM') NOT NULL,
    template_id BIGINT NOT NULL,
    template_version_id BIGINT NOT NULL COMMENT '锁定的模板版本ID',
    title VARCHAR(200) NOT NULL COMMENT '申请标题',
    applicant_id BIGINT NOT NULL COMMENT '服务端确定的申请人ID',
    department_id BIGINT NOT NULL COMMENT '提交时申请人所属部门快照',
    status ENUM('DRAFT', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'WITHDRAWN') NOT NULL DEFAULT 'DRAFT',
    total_amount_cents BIGINT NOT NULL DEFAULT 0 COMMENT '系统计算的精确总金额(单位:分)',
    current_node_seq INT NOT NULL DEFAULT 0 COMMENT '当前处于第几个审批节点',
    ref_application_id BIGINT NULL COMMENT '报销关联的已批准差旅/采购单ID',
    copied_from_id BIGINT NULL COMMENT '驳回/撤回后重新提交关联的原申请ID',
    biz_payload JSON NOT NULL COMMENT '业务扩展主字段(差旅起止时间地点/采购单一来源说明/自定义表单值)',
    snapshot_json JSON NULL COMMENT '提交时固化的审批路径规则与人员快照',
    has_risk_warning TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否触发无票异常或跨单重复票据预警',
    version INT NOT NULL DEFAULT 1 COMMENT '乐观锁版本号(并发控制核心字段)',
    submitted_at DATETIME NULL COMMENT '正式提交时间',
    completed_at DATETIME NULL COMMENT '审批终态时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_applicant_status (applicant_id, status),
    INDEX idx_dept_status_time (department_id, status, submitted_at),
    CONSTRAINT fk_app_applicant FOREIGN KEY (applicant_id) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_app_tpl_ver FOREIGN KEY (template_version_id) REFERENCES workflow_template_versions(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 采购明细与供应商报价表 (procurement_items & procurement_quotes)
CREATE TABLE procurement_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    item_name VARCHAR(128) NOT NULL COMMENT '物品或服务名称',
    specification VARCHAR(128) NOT NULL COMMENT '规格型号',
    quantity INT NOT NULL COMMENT '数量(>0)',
    unit VARCHAR(32) NOT NULL COMMENT '单位',
    unit_price_cents BIGINT NOT NULL COMMENT '预计单价(分)',
    subtotal_cents BIGINT NOT NULL COMMENT '服务端计算小计(分)',
    CONSTRAINT fk_proc_item_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE procurement_quotes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    supplier_name VARCHAR(128) NOT NULL COMMENT '供应商名称',
    quote_date DATE NOT NULL COMMENT '报价日期',
    quoted_amount_cents BIGINT NOT NULL COMMENT '报价总金额(分)',
    purchase_url VARCHAR(500) NULL COMMENT '线上购买链接',
    is_selected TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为拟选供应商',
    attachment_id BIGINT NULL COMMENT '报价单或电商截图附件ID',
    CONSTRAINT fk_proc_quote_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. 报销费用明细表 (expense_items)
CREATE TABLE expense_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    expense_type VARCHAR(32) NOT NULL COMMENT 'TRAFFIC, HOTEL, MEAL, OFFICE, OTHER',
    occur_date DATE NOT NULL COMMENT '费用发生日期',
    description VARCHAR(255) NOT NULL COMMENT '用途说明',
    amount_cents BIGINT NOT NULL COMMENT '明细金额(分, 必须>0)',
    is_no_invoice TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为无票例外支出',
    no_invoice_reason VARCHAR(255) NULL COMMENT '无票原因说明(财务界面高亮显示)',
    invoice_numbers VARCHAR(255) NULL COMMENT '关联票据号码汇总',
    CONSTRAINT fk_exp_item_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. 流程实例审批节点表 (approval_instance_nodes)
CREATE TABLE approval_instance_nodes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    node_seq INT NOT NULL COMMENT '顺序节点序号: 1, 2, 3...',
    node_name VARCHAR(64) NOT NULL COMMENT '节点名称 如: 部门负责人审批 / 财务审核',
    rule_type VARCHAR(32) NOT NULL COMMENT '规则快照: DEPT_MANAGER / ROLE / USER',
    approver_id BIGINT NOT NULL COMMENT '提交时解析确定的实际审批人ID',
    delegated_from_id BIGINT NULL COMMENT '若触发代理委托，记录原审批人ID',
    status ENUM('WAITING', 'PENDING', 'APPROVED', 'REJECTED', 'SKIPPED', 'CANCELED') NOT NULL DEFAULT 'WAITING',
    comment TEXT NULL COMMENT '审批意见或驳回理由',
    acted_at DATETIME NULL COMMENT '处理时间',
    UNIQUE KEY uk_app_node_seq (application_id, node_seq),
    INDEX idx_approver_pending (approver_id, status),
    CONSTRAINT fk_node_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. 审批与管理留痕日志表 (approval_logs)
CREATE TABLE approval_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NULL COMMENT '关联申请ID(系统级管理操作可为NULL)',
    template_version INT NULL COMMENT '当时的模板版本号',
    node_seq INT NULL COMMENT '操作的节点序号',
    node_name VARCHAR(64) NULL,
    operator_id BIGINT NOT NULL COMMENT '操作人ID',
    action ENUM('CREATE_DRAFT', 'SUBMIT', 'APPROVE', 'REJECT', 'WITHDRAW', 'RESUBMIT', 'URGE', 'DELEGATE', 'ADMIN_AUTH_CHANGE') NOT NULL,
    comment TEXT NULL COMMENT '审批意见/驳回原因/配置变更详情',
    result_status VARCHAR(32) NOT NULL COMMENT '操作后状态结果',
    ip_address VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_log_app (application_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. 附件与票据资料表 (attachments)
CREATE TABLE attachments (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    expense_item_id BIGINT NULL COMMENT '报销明细关联ID',
    file_category ENUM('QUOTE_PROOF', 'TRAVEL_DOC', 'INVOICE', 'CUSTOM_ATTACHMENT') NOT NULL,
    original_name VARCHAR(255) NOT NULL COMMENT '原始文件名',
    storage_path VARCHAR(500) NOT NULL COMMENT '服务端受控存储相对路径',
    mime_type VARCHAR(64) NOT NULL COMMENT 'image/jpeg, image/png, application/pdf',
    file_size_bytes BIGINT NOT NULL COMMENT '文件大小(<=10MB)',
    file_sha256 CHAR(64) NOT NULL COMMENT '文件SHA-256哈希(用于同单防重与跨单查重预警)',
    invoice_no VARCHAR(64) NULL COMMENT '票据号码(选填或OCR提取)',
    uploaded_by BIGINT NOT NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sha256 (file_sha256),
    INDEX idx_invoice_no (invoice_no),
    CONSTRAINT fk_att_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 11. 持久化站内通知表 (notifications)
CREATE TABLE notifications (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    recipient_id BIGINT NOT NULL COMMENT '接收用户ID',
    application_id BIGINT NULL COMMENT '关联跳转的申请单ID',
    notify_type ENUM('NEW_TODO', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'URGE_REMINDER') NOT NULL,
    title VARCHAR(200) NOT NULL,
    content VARCHAR(500) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE COMMENT '防重复通知幂等键 如: app_102_node_2_todo',
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    read_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recipient_unread (recipient_id, is_read, created_at),
    CONSTRAINT fk_notif_user FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 7. RESTful API 接口设计规范

所有接口均以 `/api/v1` 为前缀，除登录注册外均需携带 `Authorization: Bearer <JWT>` 请求头。以下为核心业务接口列表：

|**模块**|**方法**|**路径**|**功能描述**|**服务端核心校验逻辑**|
|---|---|---|---|---|
|**认证与用户**|`POST`|`/api/v1/auth/register`|新用户注册|校验用户名/邮箱唯一、密码 $\ge 8$ 位 BCrypt 加密；忽略任何客户端传入的角色字段，默认置为普通待确认员工。|
||`POST`|`/api/v1/auth/login`|登录获取 Token|验证账号状态与密码哈希，返回 JWT 及用户当前授权的角色与部门列表。|
|**系统管理**|`PUT`|`/api/v1/admin/users/{id}/roles`|管理员确认部门并授予角色|仅 `ADMIN` 可调；更新 `user_roles` 并强制写入 `approval_logs` (`ADMIN_AUTH_CHANGE`)。|
||`POST`|`/api/v1/admin/templates`|创建/发布新版本自定义流程模板|校验字段 `field_key` 唯一、节点 $\ge 2$、审批人规则可解析且无环；自动递增 `version_num`。|
|**申请管理**|`POST`|`/api/v1/applications`|保存草稿或正式提交申请|强制使用当前登录用户作为 `applicant_id`；服务端重算明细总金额（分）；提交时解析节点审批人快照。|
||`GET`|`/api/v1/applications`|分页筛选申请列表（我的/待办/部门）|支持按类型、状态、起止时间、关键词筛选；根据当前 `view_mode` 强制注入 SQL Data Scope 过滤。|
||`GET`|`/api/v1/applications/{id}`|获取申请详情、快照路径与审批历史|校验当前用户是否为申请人、审批链路节点人员或具备对应部门/财务授权，越权返回 `403 Forbidden`。|
|**审批流转**|`POST`|`/api/v1/applications/{id}/approve`|当前审批人批准节点|校验 `current_node.approver_id == user.id` 且 `user.id != applicant_id`；校验乐观锁 `version`。|
||`POST`|`/api/v1/applications/{id}/reject`|当前审批人驳回申请|强制校验 `comment`（驳回理由）非空；状态置为 `REJECTED`，终止后续节点。|
||`POST`|`/api/v1/applications/{id}/withdraw`|申请人主动撤回审批中申请|仅申请人本人且状态为 `IN_REVIEW` 时可调；与审批并发冲突时返回 `409`。|
||`POST`|`/api/v1/applications/{id}/resubmit`|驳回/撤回后一键复制并修改重提|复制原表单与明细生成新申请单，记录 `copied_from_id` 关联原记录，保留原单历史。|
|**附件与票据**|`POST`|`/api/v1/attachments/upload`|上传票据或报价凭证|校验后缀 (JPEG/PNG/PDF) 与大小 ($\le 10\text{MB}$)；计算 SHA-256 并返回是否命中跨单重复预警。|
||`GET`|`/api/v1/attachments/{id}/file`|鉴权预览或下载附件|服务端执行所属申请单的访问权限检查，通过后返回二进制文件流。|
|**统计与通知**|`GET`|`/api/v1/stats/overview`|个人/部门/财务审批统计与图表数据|明确口径：**仅按提交时间统计状态为 `APPROVED` 的申请金额**，草稿与驳回不计入通过金额。|
||`GET`|`/api/v1/notifications/stream`|SSE 实时通知订阅流|保持长连接，当产生新待办或审批结果变化时实时推送到前端/手机端免刷新弹窗。|
||`PUT`|`/api/v1/notifications/{id}/read`|标记单条或全部通知已读|强制校验 `recipient_id == current_user.id`，禁止读取或标记他人通知。|

## 8. 重点提分项与可选增强功能设计

### 8.1 重点提分：移动端全流程适配与多通道实时提醒

1. **移动端交互与响应式改造（PWA Web App）**：
    
    - 采用响应式断点设计（`< 768px` 自动切换为移动端布局），并配置 `manifest.json` 支持手机浏览器“添加到主屏幕”作为独立 App 运行。
        
    - **禁止横向滚动的多明细触控体验**：桌面端的“采购明细表”、“供应商比价表”与“报销费用表”在手机端自动渲染为**可折叠卡片列表（Card List）+ 底部抽屉式分步录入表单（Bottom Sheet Drawer）**。
        
    - **手机相机直传票据**：报销上传组件配置 `<input type="file" accept="image/jpeg,image/png,application/pdf" capture="environment">`，在手机上点击可直接唤起后置摄像头拍摄发票并自动压缩上传。
        
2. **双层实时与后台进度提醒机制**：
    
    - **第一层（页面打开时免刷新实时到达）**：通过 **SSE (Server-Sent Events)** 建立轻量级服务端单向推送通道。当员工提交申请或审批人点击批准/驳回时，相关当事人的手机/电脑页面立即弹出 Toast 提醒条并自动刷新红点计数与待办列表，点击提醒直接跳转至对应申请详情页。
        
    - **第二层（页面关闭或后台时触达）**：集成 **Web Push API (基于 VAPID 密钥协议)** 与 **SMTP 邮件异步通知**。当应用处于后台或关闭状态时，浏览器 Service Worker 接收推送并在手机系统通知栏弹出原生通知；若用户拒绝通知权限或推送网关失败，服务端捕获异常并确保持久化站内信 (`notifications` 表) 100% 写入成功，且通过幂等键 `idempotency_key` 保证网络重试绝不产生重复通知。
        

### 8.2 精选增强功能设计（提供完整演示证据）

为确保增强功能高分通过验收，本系统重点实现以下三项闭环增强能力：

1. **跨申请重复票据智能预警（Duplicate Invoice Detection）**：
    
    - **实现机制**：在 `attachments` 表对 `file_sha256`（文件内容哈希）和 `invoice_no`（发票代码+号码）建立索引。当员工提交报销单时，系统不仅阻断同单内的重复票据，还会扫描全库其他非撤回/非草稿报销单。
        
    - **演示效果**：若发现某张电子发票 PDF 或截图曾被自己或其他员工在其他报销单中使用过，系统自动将该报销单标记为 `has_risk_warning = 1`，并在部门负责人与财务审批界面顶部展示红色预警卡片：_“⚠️ 重复报销预警：明细 #2 的票据（SHA256: `8f3a...` / 票号: `2633200...`）与申请单 `EXP-20261110-000012` 存在重复，请重点核实！”_
        
2. **审批委托与超时催办（Delegation & Urging）**：
    
    - **审批委托**：部门负责人或财务出差期间，可在个人中心设置“审批委托”（指定代理人 ID、生效开始与结束时间、适用流程范围）。期间流转到该负责人的节点将自动转交代理人处理，审批日志明确记录 `由 张三 委托 李四 审批`。
        
    - **一键催办**：当申请处于 `IN_REVIEW` 且当前节点停留超过设定阈值（演示模式下支持手动立即触发，限每节点每 4 小时可催办 1 次以防骚扰），申请人点击“催办”按钮，系统向当前审批人发送高优先级站内信与邮件提醒，并在审批日志中留下 `URGE` 记录。
        
3. **可视化流程节点编辑器（Visual Workflow Designer）**：
    
    - 管理员在创建自定义流程（如“请假审批”、“公章外借”）时，通过可视化画布配置 `[开始] -> [申请人部门负责人] -> [条件分支: 天数>3天 / 金额>5000元] -> [企业负责人] -> [结束]`，直观调整节点顺序并实时预览生成的表单结构。
        

## 9. UI 界面与交互体验设计

系统遵循清晰、防误触与状态透明的设计原则：

### 9.1 导航与工作台布局

- **普通员工/审批人视角**：左侧（移动端为底部 Tab 栏）提供：`工作台首页（统计图表）`、`发起申请（采购/差旅/报销/自定义入口）`、`我的申请（含草稿箱）`、`我的待办（带实时未读角标）`、`已办事项`、`通知中心`、`个人设置（含审批委托）`。
    
- **系统管理员独立入口**：顶部切换或独立路由 `/admin`，包含：`部门与组织架构`、`用户审核与角色授权`、`自定义流程模板中心`、`系统配置与操作审计日志`。
    

### 9.2 交互反馈与防呆确认机制

- **全状态反馈**：所有列表与表单均实现 Skeleton 骨架屏加载态、空状态插画提示（Empty State）、表单字段级实时红字校验错误提示、提交成功后的单号弹窗反馈。
    
- **高危操作二次确认**：对于`删除草稿`、`撤回审批中申请`、`停用流程模板`、`驳回申请（强制弹出理由输入框）`等操作，均采用模态确认框（Modal Confirm）二次确认，并禁用提交按钮的连续点击（Loading 锁死），从源头防止误操作。
    

## 10. Docker 容器化部署与测试验证方案

### 10.1 Docker Compose 容器编排架构

项目根目录提供完整的 `docker-compose.yml` 与 `.env.example`，实现一键构建与可复现运行：

YAML

```
version: '3.9'
services:
  mysql-db:
    image: mysql:8.0
    container_name: approval-mysql
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD:-RootPass123!}
      MYSQL_DATABASE: approval_system
      TZ: Asia/Shanghai
    volumes:
      - mysql_data:/var/lib/mysql
      - ./db/init_schema_and_seed.sql:/docker-entrypoint-initdb.d/01_init.sql:ro
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 5s
      retries: 10

  backend-api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: approval-backend
    restart: always
    depends_on:
      mysql-db:
        condition: service_healthy
    environment:
      DATABASE_URL: mysql+pymysql://root:${DB_ROOT_PASSWORD:-RootPass123!}@mysql-db:3306/approval_system
      JWT_SECRET_KEY: ${JWT_SECRET_KEY:-ZjuBsCourseProjectSecretKey2026}
      UPLOAD_DIR: /app/storage/attachments
    volumes:
      - attachment_storage:/app/storage/attachments

  frontend-web:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: approval-frontend
    restart: always
    depends_on:
      - backend-api
    ports:
      - "8080:80"
```

### 10.2 预设演示账号与初始化种子数据

数据库初始化脚本 `01_init.sql` 预设完整的组织架构与演示测试账号（密码统一经过 BCrypt 哈希，明文均为 `Zju123456`），开箱即可演示全部权限边界：

|**预设用户名**|**姓名**|**所属部门**|**拥有角色**|**演示用途**|
|---|---|---|---|---|
|`admin`|系统管理员|总经办|`ADMIN`|演示部门维护、新用户转正授权、创建“请假/用章”自定义流程模板、查看审计日志。|
|`emp_rnd`|张三|研发部|`EMPLOYEE`|演示提交采购（含比价/单一来源）、差旅、关联报销（含无票异常与重复票据）、撤回与催办。|
|`emp_mkt`|李四|市场部|`EMPLOYEE`|演示跨部门数据隔离（无法查看张三的申请及附件）。|
|`mgr_rnd`|王五|研发部|`DEPT_MANAGER`, `EMPLOYEE`|演示审批研发部待办、查看研发部统计图表、测试不能跨部门看市场部数据、测试本人提交申请时不能自己审批。|
|`fin_auditor`|赵六|财务部|`FINANCE`, `DEPT_MANAGER`|演示一人兼多角、报销单财务节点审核、查看无票高亮提醒与跨单重复发票预警。|
|`ceo`|钱总|总经办|`EXECUTIVE`|演示大额采购/大额报销的终审节点审批及全公司授权统计看板。|

### 10.3 核心验收测试用例矩阵

1. **权限越权拦截测试**：使用 `emp_mkt`（市场部员工）的 Token 尝试直接调用 `GET /api/v1/applications/{张三的申请ID}` 或下载张三的发票附件，验证服务端返回 `403 Forbidden`。
    
2. **并发撤回与审批冲突测试**：同时打开两个浏览器窗口（窗口 A 为研发部员工张三，窗口 B 为研发部经理王五），对同一笔处于 `IN_REVIEW` 的申请同时点击“撤回”与“批准”，验证仅一方成功，另一方收到 `409 状态已变更` 提示，且审批日志无脏数据。
    
3. **动态自定义流程全链路测试**：使用 `admin` 在后台新建“研发设备借用申请”（含设备名称、借用天数数字框、归还日期、担保附件），配置“研发部负责人 -> 企业负责人”二级审批并启用；随后切换 `emp_rnd` 提交该申请并走完二级审批全流程。
    
4. **服务重启持久化验证**：执行 `docker compose restart` 重启所有容器后，验证已提交申请、附件预览、审批日志及未读站内信均完整保留。