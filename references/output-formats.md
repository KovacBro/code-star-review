# 输出模板

按场景选一种，不要混用。原则：**结论先行，证据随后，改进项收尾。**

---

## 1. 标准卡（默认）

用于首次评审、用户要求"详细说说"、分数低于 3 需要解释时。

```markdown
### 代码评级 · 第 3 轮 — ★★★☆☆ 3/5

**一句话**：主流程可用，边界与错误处理不足，小修后可交付。

| 维度 | 得分 | 依据 |
| --- | --- | --- |
| 需求达成 35% | 4/5 | 分页与排序已实现；缺 total，前端无法渲染页码 |
| 正确健壮 25% | 3/5 | `page=abc` 抛 500（order_api.py:22） |
| 安全副作用 15% | 4/5 | 有登录校验；size 无上限（order_api.py:23） |
| 可维护 15% | 3/5 | 查询逻辑写在路由层，未下沉 service |
| 验证充分 10% | 2/5 | 无测试，未给运行结果 |
| **加权** | **3.40** | 未命中 Gate → 3★ |

**P1 阻断**：无
**P2 应修**：入参校验 + size 上限；返回 total
**下一轮最小改进**：加 `page/size` 的类型与范围校验，补 total 字段，跑一次 `?page=0&size=100000` 验证不再 500
```

要求：
- 每行证据必须能指到位置；只有结论没有位置的，写 `未验证`。
- "下一轮最小改进"只写 1-3 条，按投入产出排序，不写愿望清单。

---

## 2. 一行卡（连续多轮 / 高频迭代）

用户明确要求"每轮都评"时，默认用这个，避免刷屏；用户说"展开"再给标准卡。

```
第 4 轮 ★★★★☆ 4/5 · 需求5 正确4 安全5 维护3 验证2 · P2：分片大小硬编码（upload.py:88）
```

变体（分数偏低时补一句原因）：

```
第 5 轮 ★★☆☆☆ 2/5 · 失败回滚缺失，重试会重复下单（order_service.py:61）；建议先补事务再继续
```

---

## 3. 严格卡（合并前 / PR 评论）

用于用户说"按最严标准"、"能不能上线"、"帮我做 code review"。

```markdown
## 代码评级：★★★☆☆ 3/5 — 不建议合并

**Gate**：G3（主要边界未处理）→ 上限 3★
**结论**：功能正确，但错误路径会留下脏数据，合并后需人工补偿。

### 阻断项（必须修）
1. `order_service.py:61` — 批量插入逐条 commit，中途失败留下半条订单，且无幂等键。改为单事务 + 幂等键。

### 应修项
2. `order_service.py:34` — 金额用 `float`，改为 `Decimal`。
3. `order_api.py:22` — `page`/`size` 未做范围校验。

### 可选项
4. 查询逻辑下沉到 repository 层。

### 验证要求
- [ ] 导入 1000 行数据，第 500 行故意抛错，确认库中 0 条脏数据
- [ ] 同一批数据重复提交，确认不产生重复订单
```

---

## 4. 英文卡

```markdown
### Code Rating · Turn 3 — ★★★☆☆ 3/5

**Verdict**: Works on the happy path; boundary and error handling gaps. Minor fixes needed.

| Dimension | Score | Evidence |
| --- | --- | --- |
| Requirements 35% | 4/5 | Pagination + sorting done; `total` missing |
| Correctness 25% | 3/5 | `page=abc` returns 500 (order_api.py:22) |
| Security 15% | 4/5 | Auth enforced; no `size` cap (order_api.py:23) |
| Maintainability 15% | 3/5 | Query logic in the route, not the service layer |
| Verification 10% | 2/5 | No tests, no run output |
| **Weighted** | **3.40** | No gate hit → 3★ |

**Blocking**: none
**Should fix**: input validation, `size` cap, return `total`
**Next step**: validate `page/size`, add `total`, verify `?page=0&size=100000` no longer 500s
```

---

## 5. 多文件改动

Gate 按**最差文件**定，维度分按改动量加权平均，并单列风险最高处。

```markdown
### 代码评级 · 第 7 轮 — ★★☆☆☆ 2/5

**Gate**：G2 — `migration/003_drop_column.sql` 会丢数据（不可逆）

| 文件 | 星级 | 关键问题 |
| --- | --- | --- |
| `api/order.py` | ★★★★☆ | 无 |
| `service/order.py` | ★★★☆☆ | 缺事务边界 |
| `migration/003_drop_column.sql` | ★☆☆☆☆ | 直接 DROP COLUMN，无备份/回滚 |
```

---

## 6. 批量汇总（多轮趋势）

用 `score.py --summary` 生成，或手写：

```markdown
### 本次会话代码评级汇总

| 轮次 | 星级 | 加权 | 主要问题 |
| --- | --- | --- | --- |
| 1 | ★★★☆☆ | 3.1 | 无入参校验 |
| 2 | ★★★★☆ | 4.0 | 缺 total |
| 3 | ★★★★☆ | 4.2 | 无测试 |
| 4 | ★★★★★ | 4.7 | — |

**均值 4.0★ · 趋势 ↑ · 最弱维度：验证（2.5/5）**
**建议**：把"每轮附运行证据"固化为流程，否则星级会虚高。
```

---

## 7. 不该出卡的轮次

以下情况**不出评分卡**，一句话说明即可，避免噪音：

- 本轮没有代码变更（纯问答、查资料、解释概念）。
- 只是执行命令/查看文件，未产出代码。
- 用户在讨论方案、还没让写代码。

固定说法：

```
本轮无代码产出，不评分。方案确认后我再对实现打分。
```
