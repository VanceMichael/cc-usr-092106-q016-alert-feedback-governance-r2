# 命中反馈治理后台设计

> 范围：监管线索命中后，从核查反馈到可训练标签、再到上线监控与审计追溯的治理闭环。
> 本文描述的实体、规则与流程均由 `contracts/` 下的契约和 `src/` 下的纯函数实现承载，
> 可直接用 `fixtures/` 中的虚构数据验证。

## 1. 要解决的核心问题

四轮全国排查下发了近两百万条线索。把"未立案"一刀切当成负样本会同时犯四种错误：

| 实际情形 | 表面状态 | 若当负样本的后果 |
|---|---|---|
| 证据暂缺，核查未完成 | 未立案 | 把"还没查清"教成"没问题"，系统性压低风险排序 |
| 合法例外（豁免、按时披露） | 未立案 | 这是真阴性，但必须有豁免批文等独立证据支撑 |
| 数据错误（主键碰撞、串档） | 未立案 | 触发前提不成立，应从样本中更正后作为阴性 |
| 确认违法但未达立案标准 | 未立案 | **这是正样本**，按阴性处理会直接毒化规则优化方向 |

因此系统不能只保存一个二值结论，而要保存**触发来源、输入水位、分派范围、核查阶段、
结构化结论、证据依据与签发权限**，并把"什么数据能进训练集"作为一条独立、可审计的
治理流水线。

## 2. 实体模型

```
Lead（线索反馈）                 Reviewer（复核者）
  ├─ trigger 规则/模型+版本         ├─ 角色：investigator / senior_reviewer / auditor
  ├─ input_watermark 输入水位       ├─ 区域辖区（可全国）
  ├─ dispatch 分派范围              └─ 在职状态
  ├─ stage 核查阶段
  └─ conclusion 结构化结论                │ 只有 senior_reviewer + 辖区 + 在职可签发
                                         ▼
                              LabelRecord（标签版本，只追加）
                                ├─ positive / negative / excluded
                                ├─ basis：结论、证据登记号、证据充分性、来源
                                │   （field_check / appeal / case_outcome）
                                ├─ version 单调递增，supersedes_version 指向前版
                                └─ status：issued / superseded / revoked
                                         │
                    ┌────────────────────┴───────────────────┐
                    ▼                                         ▼
          Snapshot（脱敏训练快照）                  Deployment + Metrics（上线监控）
            ├─ cutoff 标签水位                         ├─ 版本、上线时点
            ├─ train/validation/test 时间切分           ├─ 前后窗口命中分布
            ├─ records（仅稳定标签）                    └─ 人工负担、正例率
            ├─ excluded[] 排除码+原因                         │
            └─ manifest 计数与脱敏变换                        ▼
                    │                                 Audit Trail（指标→线索→版本→证据→签发人）
                    ▼
          BatchReport（批次可用性说明，模型负责人签发）
```

契约文件：`contracts/lead.schema.json`、`reviewer.schema.json`、`label.schema.json`、
`snapshot.schema.json`、`deployment.schema.json`、`metrics.schema.json`、
`batch_report.schema.json`。

## 3. 核查阶段与结论语义

核查阶段（`lead.stage`）：`new → assigned → checking → concluded → closed`，
已结案线索经申诉可进入 `appealed`。前三个阶段为**未结案**，一律不产生训练标签。

结构化结论（`lead.conclusion.outcome`）与标签映射（`src/labels.py`）：

| 结论 | 含义 | 处置 |
|---|---|---|
| `violation_filed` | 违法且已立案 | positive |
| `violation_unfiled` | 确认违法、未达立案标准 | **positive**（不是负样本） |
| `legal_exception` | 合法例外，证据齐备 | negative |
| `data_error` | 源数据错误已更正 | negative（前提不成立的阴性） |
| `insufficient_evidence` | 证据暂缺 | **不签发任何标签**，快照按结论排除，补证后走新版本 |
| `rule_self_proof` | 结论仅复述规则命中，无独立证据 | 可登记 excluded 标签，快照排除 |
| `duplicate_pending` | 跨区域重复待主办裁决 | 可登记 excluded 标签，快照排除 |
| `pending` | 尚未完成 | 拒绝签发 |

## 4. 标签签发治理

签发入口：`LabelLedger.issue()`，守卫按固定顺序执行：

1. **结案门控**：线索必须已结案且有结构化结论；
2. **权限门控**（`src/reviewers.py`）：签发人须为在职 `senior_reviewer`，且辖区覆盖
   线索区域；调查员（investigator）可提交核查结论但不能自行升级为稳定标签，
   审计员（auditor）只读；
3. **结论门控**：证据暂缺/未完成直接拒绝，不产生任何标签；
4. **证据门控**：必须登记证据材料号，且签发人确认 `evidence_sufficient=true`，
   否则 positive/negative 稳定标签一律拒签；
5. **版本门控**：已存在生效标签时，普通核查（field_check）不得覆盖；只有
   **申诉（appeal，须登记 appeal_id）**或**后续案件结果（case_outcome，须登记
   case_ref）**能产生新版本。

版本只追加、不覆盖：新版本写入后旧版本置为 `superseded`；发现签发错误可 `revoke`
当前版本（记录撤销时间与原因）。这样任何时点的训练快照都能还原"当时依据的是哪一版
结论"。

## 5. 稳定标签准入与排除码

`src/eligibility.py` + `src/snapshot.py` 按以下顺序判定每条线索，排除记录均带
机器码与人类可读原因，进入快照的 `excluded` 清单：

| 排除码 | 触发条件 |
|---|---|
| `open_case` | 核查阶段仍为 new/assigned/checking |
| `insufficient_evidence` | 结论为证据暂缺（无标签），防止"未立案=阴性" |
| `cross_region_duplicate` | 跨区域组待裁决，或同主体多条均合格时仅留主办一条（标签稳定最早者） |
| `rule_self_proof` | 规则自证：被评估规则的产出不能作为监督该规则的标签 |
| `revoked_label` | 当前标签版本已撤销 |
| `settling_window` | 签发后未经过 `min_label_settled_days` 冷静期，仍可能被申诉推翻 |
| `outside_cutoff` | 标签稳定时间晚于快照水位 |
| `evidence_not_sufficient` | 历史标签未确认证据充分性或缺证据登记号 |
| `duplicate_cross_split` | 同一主体已出现在更早的时间分区，防止跨分区泄漏 |
| `no_label` | 已结案但无任何生效标签，且无策略性结论对应 |
| `permission_denied` | 为跨系统对接保留的权限不符码 |

**冷静期**是关键的标签稳定性装置：新签发标签即使证据充分，也须稳定 N 天后才能进入
快照；期间被新版本推翻或撤销会自动剔除。

## 6. 脱敏快照与时间切分

快照（`build_snapshot()`）是训练唯一允许消费的产物，构建时执行：

1. 逐条准入判定（上节）；
2. 跨区域组归并去重；
3. 水位与冷静期校验；
4. **按标签稳定时间**（不是线索创建时间）划分 `train < train_end ≤
   validation < validation_end ≤ test`，避免用"未来才翻案"的标签训练过去的数据；
5. 同主体跨分区防泄漏：主体已进更早分区时，后续线索整条排除；
6. 脱敏变换（记入 `manifest.transformations`）：
   - 主体标识 → 加盐 SHA-256 假名（换盐即换名，同盐可跨表对齐）；
   - 区县代码 → 省级大区桶（north/east/...），不下沉；
   - 标签稳定时间按月取整；
   - 删除叙述性结论与证据登记号原文，仅保留版本号与时间引用。

`manifest` 的 lead/included/excluded/正负例/分区计数必须与记录严格自洽，
`BatchReport`（`src/batch_report.py`）再从排除清单聚合出**模型负责人批次说明**：
为什么可用、每个排除码多少条、谁背书、用于哪个训练用途。无可纳入记录时
`usable=false`。

## 7. 上线后监控

新版本规则/模型上线在 `deployments` 中登记版本、上线时点与前后窗口。
`compare_deployment()`（`src/monitoring.py`）以命中时间相对上线时点强制重算
pre/post 归属（标错窗口直接报错），对比：

- **命中分布**：命中量、区域分布；
- **人工负担**：需人工复核比例、总复核分钟、单条平均复核分钟；
- **质量代理**：已出正负标签样本中的 positive_rate（excluded、未结、撤销不进分母）。

每个聚合结果保留 `lead_ids` 明细，保证任何指标数字都可以下钻。

## 8. 审计链路

`src/audit.py` 的 `trace_leads()` 从指标或快照中的 lead_id 还原：

```
指标数字 → lead_id → 触发规则/模型版本 → 输入水位 → 全部标签版本
         → 每版结论/证据登记号/证据充分性/来源(含 appeal_id、case_ref)
         → 签发人及其姓名 → 版本取代关系与撤销记录
```

审计员因此可以回答两类问题：

- **模型负责人**：这批反馈为什么可用（水位、冷静期、切分、脱敏）、哪些被排除
  （逐码计数与逐条 lead_id）、新规则改变了什么（前后窗口 delta）；
- **审计人员**：从任一指标数字一路回到具体的签发依据和签发人。

## 9. 模块与验证

| 模块 | 职责 |
|---|---|
| `src/validation.py` | 零依赖 JSON Schema 子集校验（含 date-time 时区强制） |
| `src/contracts.py` | 契约装载 |
| `src/leads.py` | 线索装载、结案判定 |
| `src/reviewers.py` | 角色/辖区/在职权限 |
| `src/labels.py` | 结论→标签映射、签发守卫、版本流转 |
| `src/eligibility.py` | 稳定标签准入与排除码 |
| `src/snapshot.py` | 去重、切分、脱敏、快照清单 |
| `src/batch_report.py` | 批次可用性说明 |
| `src/monitoring.py` | 上线前后窗口指标对比 |
| `src/audit.py` | 指标→签发依据追溯 |

```bash
python3 -m unittest discover -s tests   # 40 个用例
```

`fixtures/` 中 18 条虚构线索覆盖：立案、违法未立案、合法例外、证据暂缺、数据错误、
规则自证、跨区域重复（主办/副本/待裁决三种）、未结案、撤销、申诉 v2、冷静期内、
超水位、历史证据字段缺失、跨分区泄漏等全部路径。所有主体、证据号、人员均为虚构。
