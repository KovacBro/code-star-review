# code-star-review Skill 评估与优化计划

- 评估日期：2026-10-20
- 评估对象：`SKILL.md`、`references/rubric.md`、`references/calibration.md`、`references/output-formats.md`、`assets/auto-review-snippet.md`、`scripts/score.py`
- 评估方法：结构审查、规则一致性交叉核对、校准案例加权值复算、脚本实际运行验证

---

## 一、总体结论

**Skill 本体按其自身标准约为 4/5 星（良好，可直接使用，有少量可优化项）。**

设计成熟度高：Gate 封顶 + 五维加权 + 证据制的三层结构能显著抑制 AI 评分通胀；渐进式披露（SKILL.md 主干 + references 细则 + scripts 工具）符合 skill 最佳实践；校准案例的"为什么不是更高/更低"写法是打分一致性的关键保障。主要短板集中在**跨平台兼容性**和**脚本易用性**两处，均可在小改动内解决。

---

## 二、优点（应保留的设计）

1. **Gate 先行的判定顺序**（`SKILL.md` §2、`rubric.md` §1）：先封顶后加权，防止"五维平均掩盖致命伤"，案例 C2（路径穿越上传被从 3 星压到 1 星）证明了该机制有效。
2. **证据制纪律**（`SKILL.md` §6）：每个扣分必须指到 `file:line`，指不出证据不扣分——这是防止 AI 凭感觉打分的核心约束。
3. **反通胀条款**：`全维 4 分 ≠ 5 星`、`能跑最多 3 星`、`验证不可口头认定（≤2 分）`，直接封堵最常见的虚高路径。
4. **校准案例质量高**：全部 6 个案例的加权分我已复算，均正确（B=4.10、C=3.25、D=3.30），且每个案例都解释了"为什么不是更高/更低星"。
5. **文档与脚本阈值完全一致**：`SKILL.md` §4 的映射（≥4.6→5 等）与 `score.py` 的 `THRESHOLDS` 逐项吻合。
6. **脚本健壮性**：`build()` 对 `--gate 0` 使用 `is not None` 判断（`score.py:68`），0 星封顶不会被当 falsy 吞掉；`summarize()` 对坏行、缺文件均有容错（`score.py:107-115`）。
7. **一行卡压刷屏**（`output-formats.md` §2）与"不该出卡的轮次"（§7）考虑了实际对话体验。

---

## 三、问题清单

| 编号 | 级别 | 问题 | 位置 |
| --- | --- | --- | --- |
| O1 | **P2** | **Windows 兼容性**：所有示例命令用 `python3`，当前环境为 win32 + PowerShell，通常只有 `python`，照抄示例会直接报错 | `SKILL.md:102-108`、`auto-review-snippet.md:46` |
| O2 | **P2** | **仅汇总时也必须传五个分值**：`--need` 等五个参数为 `required=True`，用户只想看 `--summary` 时被迫编造分值；且此时编造的分值还会被追加进日志，污染数据 | `score.py:162-164` |
| O3 | **P3** | **缺少获取 diff 的操作指引**：skill 要求"优先看 diff"，但没告诉 AI 用什么命令拿 diff（`git diff HEAD` / `git diff --staged`），不同工具环境下行为可能不一致 | `SKILL.md` §1 |
| O4 | **P3** | **双轨扣分体系可能引起执行摇摆**：`rubric.md` §4 的扣分参考与 §2 锚点并行，虽有"以锚点为准"声明，但建议在 SKILL.md 主干也提一句，避免 AI 按加减法凑分 | `rubric.md:116-132` |
| O5 | **P3** | **脚本零测试**：阈值映射、Gate 封顶、auto_caps、趋势计算均无自动化测试，改动权重时容易回归出错 | `scripts/` |
| O6 | **P3** | **触发词覆盖不全**：description 未含"打几分""自评""质量分"等口语变体，可能漏触发 | `SKILL.md:3` |
| O7 | **P3** | **占位符路径易被照抄**：`auto-review-snippet.md:46` 用 `<skill>/scripts/score.py` 占位，AI 可能不替换直接执行 | `auto-review-snippet.md` |
| O8 | **P3** | **终端输出对齐瑕疵**：`render()` 用 `{:<6}` 对齐中文标签，宽字符下会错位（纯外观，不影响功能） | `score.py:90` |

---

## 四、优化建议

### 短期（小改动，建议下一轮完成）

1. **O1**：`SKILL.md` §7 和 `auto-review-snippet.md` 的命令改为双写法，例如
   `python scripts/score.py ...`（Windows）`/ python3 scripts/score.py ...`（macOS/Linux），或在命令块上方注明"Windows 下用 `python`"。
2. **O2**：`score.py` 将五个维度分改为可选，新增 `--summary-only` 语义：当只传 `--summary` 且未传任何维度分时，仅输出汇总、不写日志、不评分。
3. **O3**：在 `SKILL.md` §1 追加一行工具提示：
   > 取 diff：`git diff HEAD`（本轮改动）或 `git diff --staged`（已暂存）；无法取 diff 时按用户提供/刚生成的代码段圈定范围。
4. **O6**：description 追加触发变体：`"打几分"、"自评一下代码"、"质量分"`。

### 长期（迭代方向）

5. **O5**：新增 `scripts/test_score.py`（纯标准库 `unittest` 即可），至少覆盖：
   - 阈值边界（4.59→4★，4.60→5★）；
   - `--gate 0` 不被吞；
   - auto_caps 触发（security=1 → 封顶 1，security=2 → 封顶 2）；
   - summarize 的坏行容错与趋势计算。
6. **O4**：在 `SKILL.md` §4 末尾补一句："扣分参考只用于校准，最终以 `rubric.md` 锚点为准，不做加减法凑分。"
7. **O7**：`auto-review-snippet.md` 中的命令示例改为要求 AI "替换为 skill 实际绝对路径"，并给出 Windows / Unix 两种写法示例。
8. **O8**：`render()` 的中文标签对齐可改为手动 pad 或按显示宽度计算；优先级最低。
9. **可扩展方向**：
   - 支持从 `git diff` 自动提取改动文件清单，附在评分卡中；
   - `--summary` 增加 JSON 输出，方便外部工具消费；
   - 校准案例增加非 Python 语言案例（前端/SQL 迁移脚本），减少语言偏差。

---

## 五、验证记录

1. 校准案例 A-F 加权分复算：全部正确。
2. `SKILL.md` 星级映射 vs `score.py` `THRESHOLDS`：一致。
3. `--gate 0` 的 `is not None` 处理：正确，0 星封顶可用。
4. 脚本实际运行验证（评分、封顶、日志、汇总）见本轮对话末尾的实评记录；`--summary` 单独调用报 `argparse` 缺参错误，证实 O2。

---

## 六、结论

该 skill 可直接投入使用，规则体系自洽、防通胀机制完善。按第四节短期项（O1/O2/O3/O6）修完即可达到其自身定义的 5 星标准；长期项按需排期。

---

## 七、修复记录（2026-10-20）

上节问题已全部修复，验证方式见备注：

| 编号 | 状态 | 修复方式 |
| --- | --- | --- |
| O1（P2） | 已修复 | `SKILL.md` §7、`scripts/score.py` docstring、`auto-review-snippet.md` 命令均改为 Windows（`python`）/ macOS-Linux（`python3`）双写法 |
| O2（P2） | 已修复 | `score.py` 五维分改为可选：仅传 `--summary` 进入只读汇总模式（不评分、不写日志）；全缺/缺维时报明确错误 |
| O3（P3） | 已修复 | `SKILL.md` §1 补充 `git diff HEAD` / `git diff --staged` 取 diff 指引 |
| O4（P3） | 已修复 | `SKILL.md` §4 末尾补充"扣分参考仅用于校准，以 `rubric.md` §2 锚点为准" |
| O5（P3） | 已修复 | 新增 `scripts/test_score.py`（15 个用例：阈值边界、Gate 0、auto_caps、汇总容错与趋势、仅汇总模式、缺参报错、日志写入） |
| O6（P3） | 已修复 | description 补充"打几分、自评、质量分"触发变体 |
| O7（P3） | 已修复 | `auto-review-snippet.md` 占位符改为要求替换实际安装路径，并给出 Windows/Unix 示例 |
| O8（P3） | 已修复 | `score.py` `render()` 改为按显示宽度（全角 2 列）对齐 |

验证：`python scripts/test_score.py` 全部通过；`--summary` 单独调用不再报错。
