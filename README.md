# ♻️ 回收分拣来料污染判定系统

面向回收分拣场站的来料污染判定 Web 应用：提交**批次编号、来源区域、重量、检验物料类别与污染量**，
系统按照**可版本化的接收规则**自动计算污染等级、处置结论、扣费明细与证据说明；
支持判定单保存/查询/CSV 导出与完整审计记录。

技术栈：FastAPI + SQLAlchemy 2 + SQLite（可通过环境变量切换其他数据库）+ 原生 HTML/JS 页面。

---

## 一、核心业务规则

### 判定输入
| 字段 | 说明 |
| --- | --- |
| `batch_no` | 批次编号 |
| `region` | 来源区域（如 `EAST_CN`、`SOUTH_CN`） |
| `weight_kg` | 来料总重量 (kg)，必须 > 0 |
| `items[]` | 检验明细：`material_code` 物料类别 + `contamination_kg` 污染量 |
| `rule_version` | 可选；缺省使用该区域**当前生效**规则版本 |

### 拒绝判定（返回 422 字段级错误，不出具结论）
- **未知类别**：物料代码未在规则版本中定义；
- **负重量**：`weight_kg < 0`（0 同样拒绝）；
- **负污染量**：任一明细污染量为负；
- **污染量超过重量**：污染量合计 > 来料重量；
- 区域没有生效规则、指定版本不存在或不属于该区域。

错误响应统一为：
```json
{
  "error": "field_validation_failed",
  "errors": [
    {"field": "weight_kg", "message": "重量不能为负数"},
    {"field": "items.material_code", "message": "未知物料类别: FOO（规则 v2026.1 未定义）"}
  ]
}
```

### 计算逻辑
1. 同类别多行先聚合；总污染率 = 污染量合计 / 重量。
2. 按规则中的污染等级区间定级（默认 A 轻微 ≤3% / B 一般 ≤8% / C 严重 ≤15% / D 高危）。
3. **强制拒收触发条件**（任一即拒收，零结算）：
   - 总污染率超过规则上限（默认 30%）；
   - 任一物料类别污染率超过该类别单独允许上限（如 PET 8%、GLASS 5%）。
4. 处置结论默认映射：A → `ACCEPT 合格接收`；B/C → `ACCEPT_FEE 接收扣费`；D → `CONDITIONAL 有条件接收/人工复核`；触发拒收 → `REJECT 拒收`。
5. 扣费明细：按各物料 `污染量 × 该类别扣费单价(元/kg)` 逐项列出计算依据；拒收批次扣全部货值、应付 0。
6. 所有金额按 **四舍五入保留 2 位小数**（Decimal 计算），污染率保留 4 位小数。
7. 每条结论附带中文**证据说明**（依据版本、污染率、阈值、扣费算式、触发原因）。

### 规则版本化与历史结论固化（关键设计）
- 规则以「版本 + 区域」组织（如 `EAST_CN/v2026.1`），每个区域**同时只有一个生效版本**，可随时切换；
- 创建新版本、切换生效版本均为独立操作，旧版本始终保留可查；
- **出具判定单时，将当时规则集整体 JSON 快照存入判定单**（`rule_snapshot`）。
  之后无论规则如何更新、区域如何切换，历史判定单的等级、结论、扣费与证据都不会改变；
- 仍可在请求中显式传 `rule_version`，用历史版本为新批次出具判定。
- 判定单一经出具**不可编辑、不可删除**。

### 审计
以下操作自动写入 `audit_logs`：`decision.create`、`decision.dry_run`、`decision.export`、
`rule.create`、`rule.activate`，包含操作人（取 `X-Operator` 请求头）、对象引用与变更详情。

---

## 二、一键启动（Docker Compose）

```bash
docker compose up -d --build
```

启动后：

| 地址 | 内容 |
| --- | --- |
| http://localhost:8000/ | 简洁页面（来料判定 / 查询 / 规则版本 / 审计 四个标签页） |
| http://localhost:8000/docs | Swagger UI（在线调试所有 API） |
| http://localhost:8000/healthz | 健康检查 |

数据持久化在 Docker volume `recycle-data`（容器内 `/data/recycle.db`）。

首次启动自动写入种子规则：
- `EAST_CN / v2026.1`（生效）与 `v2026.2-draft`（更严格草案：总污染率上限 20%、扣费上浮 20%）
- `SOUTH_CN / v2026.1`（生效）

内置物料：`PET、HDPE、PP、PAPER、GLASS、METAL、ALU、ORGANIC`。

### 本地直接运行（无 Docker）

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 配置项（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/recycle.db`（容器内 `sqlite:////data/recycle.db`） | 数据库连接串，可换 PostgreSQL/MySQL 等 |
| `APP_NAME` | 回收分拣来料污染判定系统 | 页面标题 |
| `APP_ENV` | `dev` | 环境标识（健康检查回显） |

运行测试：

```bash
pip install -r requirements.txt
python -m pytest -q
```

---

## 三、HTTP API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/decisions` | 出具判定单（`dry_run=true` 仅试算不落库） |
| GET | `/api/decisions` | 列表查询（`batch_no / region / grade / limit / offset`） |
| GET | `/api/decisions/{decision_no}` | 查询单张判定单（含规则快照） |
| GET | `/api/decisions/export/csv` | 按当前筛选条件导出 CSV（带 BOM，Excel 直开） |
| GET | `/api/rules/regions` | 区域及当前生效版本 |
| GET | `/api/rules?region=` | 规则版本列表 |
| POST | `/api/rules` | 创建规则版本（可 `activate=true` 直接生效） |
| GET | `/api/rules/{id}` | 查看某版本规则内容（含历史版本） |
| POST | `/api/rules/{id}/activate` | 区域规则切换：激活该版本 |
| GET | `/api/audit-logs` | 审计记录查询（`action / entity_type / entity_ref`） |

> 可通过 `X-Operator: 工号` 请求头标识操作人，会写入审计记录。

---

## 四、API 调用示例

### 1) 出具判定单（接收扣费）

```bash
curl -X POST http://localhost:8000/api/decisions \
  -H 'Content-Type: application/json' \
  -H 'X-Operator: inspector-07' \
  -d '{
    "batch_no": "BATCH-20261005-01",
    "region": "EAST_CN",
    "weight_kg": 1000,
    "items": [
      {"material_code": "PET",   "contamination_kg": 50},
      {"material_code": "GLASS", "contamination_kg": 2}
    ]
  }'
```

响应节选：

```json
{
  "decision_no": "RC20261005171050970",
  "persisted": true,
  "rule_version": "v2026.1",
  "total_contamination_kg": 52.0,
  "contamination_rate": 0.052,
  "grade": "B",
  "conclusion_code": "ACCEPT_FEE",
  "conclusion": "接收扣费",
  "gross_amount": 2500.0,
  "deductions": [
    {"type": "CONTAMINATION_FEE", "name": "PET瓶(PET) 污染扣费",
     "contamination_kg": 50.0, "unit_price": 1.2, "amount": 60.0,
     "basis": "50.0kg × 1.2 元/kg"},
    {"type": "CONTAMINATION_FEE", "name": "玻璃(GLASS) 污染扣费",
     "contamination_kg": 2.0, "unit_price": 0.4, "amount": 0.8,
     "basis": "2.0kg × 0.4 元/kg"}
  ],
  "total_deduction": 60.8,
  "net_payable": 2439.2,
  "evidence": [
    "依据规则版本 v2026.1（区域 EAST_CN）计算，结论出具时已固化该版本快照。",
    "来料重量 1000.0kg，污染量合计 52.0kg，总污染率 0.0520（原始 0.0520）。",
    "总污染率判定等级：B（一般），阈值上限 0.08。",
    "结论 ACCEPT_FEE（接收扣费）对应等级 ['B', 'C']。",
    "货值 2500.00 元（1000.0kg × 2.5 元/kg），扣费合计 60.80 元，应付 2439.20 元。"
  ],
  "rule_snapshot": { "...": "出具当时完整规则，后续规则变更不影响本单" }
}
```

### 2) 仅试算，不落库

```bash
curl -X POST http://localhost:8000/api/decisions \
  -H 'Content-Type: application/json' \
  -d '{"batch_no":"TRY-1","region":"EAST_CN","weight_kg":1000,
       "items":[{"material_code":"PET","contamination_kg":50}],
       "dry_run": true}'
```

### 3) 字段错误被拒绝（未知类别 + 负重量）

```bash
curl -i -X POST http://localhost:8000/api/decisions \
  -H 'Content-Type: application/json' \
  -d '{"batch_no":"BAD-1","region":"EAST_CN","weight_kg":-10,
       "items":[{"material_code":"FOO","contamination_kg":5}]}'
# HTTP/1.1 422 Unprocessable Entity
# {"error":"field_validation_failed","errors":[
#   {"field":"weight_kg","message":"重量不能为负数"},
#   {"field":"items.material_code","message":"未知物料类别: FOO（规则 v2026.1 未定义）}"}]}
```

### 4) 查询 / 指定历史规则版本出具

```bash
# 按批次查询
curl 'http://localhost:8000/api/decisions?batch_no=BATCH-20261005-01'

# 区域已切换到新版本后，仍可指定旧版本为新批次出具
curl -X POST http://localhost:8000/api/decisions \
  -H 'Content-Type: application/json' \
  -d '{"batch_no":"BATCH-20261005-09","region":"EAST_CN","weight_kg":800,
       "items":[{"material_code":"PAPER","contamination_kg":10}],
       "rule_version":"v2026.1"}'
```

### 5) 区域规则切换

```bash
# 查看华东区域版本
curl 'http://localhost:8000/api/rules?region=EAST_CN'

# 激活草案版本（同区域其他版本自动失效）
curl -X POST http://localhost:8000/api/rules/2/activate -H 'X-Operator: supervisor'
```

### 6) 创建新规则版本

```bash
curl -X POST http://localhost:8000/api/rules \
  -H 'Content-Type: application/json' \
  -d '{
    "version": "v2027.1",
    "region": "EAST_CN",
    "note": "2027 年度规则",
    "activate": true,
    "content": {
      "base_price_per_kg": 2.6,
      "currency": "CNY",
      "reject_pays_zero": true,
      "max_total_contamination_rate": 0.25,
      "materials": {
        "PET": {"name": "PET瓶", "deduct_price_per_kg": 1.3,
                "max_allowable_rate": 0.07, "level_rates": {"A": 0.02, "B": 0.05}}
      },
      "levels": [
        {"code": "A", "name": "轻微", "max_rate": 0.03},
        {"code": "B", "name": "一般", "max_rate": 0.08},
        {"code": "C", "name": "严重", "max_rate": 0.15},
        {"code": "D", "name": "高危", "max_rate": 1.0}
      ],
      "conclusions": {
        "ACCEPT":      {"code": "ACCEPT",      "label": "合格接收", "grades": ["A"]},
        "ACCEPT_FEE":  {"code": "ACCEPT_FEE",  "label": "接收扣费", "grades": ["B", "C"]},
        "CONDITIONAL": {"code": "CONDITIONAL", "label": "有条件接收/人工复核", "grades": ["D"]},
        "REJECT":      {"code": "REJECT",      "label": "拒收", "grades": []}
      }
    }
  }'
```

### 7) 导出 CSV 与查询审计

```bash
# 导出（可叠加 batch_no / region / grade 过滤）
curl -o decisions.csv 'http://localhost:8000/api/decisions/export/csv?region=EAST_CN'

# 审计：谁在什么时候切换了规则
curl 'http://localhost:8000/api/audit-logs?action=rule.activate'
```

### Python 调用示例

```python
import httpx

resp = httpx.post(
    "http://localhost:8000/api/decisions",
    headers={"X-Operator": "inspector-07"},
    json={
        "batch_no": "BATCH-20261005-01",
        "region": "EAST_CN",
        "weight_kg": 1000,
        "items": [{"material_code": "PET", "contamination_kg": 50}],
    },
    timeout=10,
)
resp.raise_for_status()
result = resp.json()
print(result["grade"], result["conclusion"], result["net_payable"])
```

---

## 五、目录结构

```
.
├── app/
│   ├── main.py              # FastAPI 入口、统一 422 错误处理
│   ├── config.py            # 环境配置
│   ├── db.py / models.py    # 数据库与 ORM（规则集 / 判定单 / 审计）
│   ├── engine.py            # 纯函数判定引擎（校验、定级、扣费、证据）
│   ├── schemas.py           # 请求/响应模型
│   ├── seed.py              # 初始规则（幂等）
│   ├── audit.py             # 审计写入
│   ├── services/            # 规则版本服务 / 判定单服务（快照固化、CSV）
│   ├── routers/             # decisions / rules / audit-logs 路由
│   ├── templates/index.html # 简洁页面
│   └── static/              # style.css / app.js
├── tests/                   # 引擎单测 + API 端到端测试（20 个）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```
