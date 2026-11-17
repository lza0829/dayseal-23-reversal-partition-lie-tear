# Dayseal（日封台）

收银流水按营业日归集，日结封账后锁定；长短款可查；错账通过冲正处理，原流水只读留痕。

- 前端 http://127.0.0.1:5700
- API http://127.0.0.1:10700

## 冲正命运（全局互斥，只贯彻一种）

策略存于 `settings.reversal_policy`，在「设置」页切换，全系统同一时刻只有一种生效：

- **同日对冲 `same_day`（默认）**：冲正必须落在原流水同一 `business_day`，生成等额负向流水并通过 `reversal_of_line_no` 引用原 `line_no`；若该日已 `sealed` 且系统未实现解封，则直接拒绝（HTTP 409），不撬已封日。对冲后净额进入该日封账合计。
- **冲正日另计 `current_day`**：冲正落入发起时的当前营业日，原日已封合计保持不变；冲正日合计含负向额。`reversals` 表同时保存原单号、冲正单号、两个营业日与所用策略，流水与批次均可溯源原 `line_no`。

约定：

- 冲正唯一入口 `POST /api/lines/{id}/reverse`，普通登记入口拒绝负金额。
- 原流水与冲正流水均为只读：禁止修改、禁止物理删除，禁止重复冲正，禁止用删除原流水冒充冲正。
- 有效合计只有一个口径：`lines.day_summary()`，封账预览、封账落批、仪表盘同源，负向冲正额以负数参与求和。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/lines/{id}/reverse` | 冲正入口（body 可空，可带 note） |
| GET | `/api/lines/reversals/all` | 冲正溯源列表 |
| GET/PUT | `/api/settings/reversal-policy` | 读取/切换全局冲正策略 |
| GET | `/api/close/preview` | 封账预览（与封账同口径，含冲正笔数） |

## 启动

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 10700 --app-dir .
```

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5700
```

## 测试

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

覆盖：未封同日对冲（净额入封账合计）、冲正日另计（原日已封不变、负向额落冲正日）、已封日同日冲正无解封被拒、只读链与禁止物理删除、策略枚举互斥校验，以及「原单消失无冲正 / 冲正进已封分区 / 双边重复扣」三夹具互证（事实侧流水+引用链 ↔ 度量侧预览/批次/仪表盘同源）。
