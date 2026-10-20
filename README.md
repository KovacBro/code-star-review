# code-star-review · 代码星级评审（开源版）

给 AI 开发过程中每一轮生成或修改的代码做 0-5 星级质量评审（0=无效/有害，5=可直接合并）；也支持对日常问答、分析结论等非代码输出评分（`--mode qa`）。

每轮只回答三个问题：**这段代码现在能不能用？值几星？下一轮最该修什么？**

- 五维加权（需求达成 35% / 正确健壮 25% / 安全副作用 15% / 可维护 15% / 验证充分 10%）+ Gate 封顶 + 证据制评分卡
- 自动取证（`--diff`）、验证联动（`--run-tests`）、多评审中位（`--median`）、趋势报告（`--report`）
- 项目配置（`.star-review.yaml`）、CI 门禁（`--min-stars`）、评分与修复闭环（`--fix`）
- 问答模式（`--mode qa`）可给非代码输出打分

安装与使用详见 [SKILL.md](SKILL.md)，更新记录见 [CHANGELOG.md](CHANGELOG.md)。

## Pro 版

本仓库是开源版。Pro 版拥有开源版全部功能，并以更低 token 消耗、更高效率完成同等评审：

👉 **[SkillPay 购买 / 了解 Pro 版](https://skillpay.alipay.com/public/whensing)**

## 开源版 vs Pro 版（当前版本）

开源版 `1.0.0`，Pro 版 `1.0.0-pro`（功能基线对齐，含开源版全部 v1.0 功能：`--init` 脚手架、`--format md|json` + `--out`、CLI 接口冻结承诺）。Pro 独有功能，开源版不会实现：

| 功能 | Pro 命令 | 省什么 |
| --- | --- | --- |
| 一行卡直出 | `--emit line` | AI 不再手写评分卡，直接引用脚本输出，每轮省一次卡片组装 |
| 紧凑输出 | `--compact` | 砍掉 diff 明细与验证输出尾巴，输出行数约减 40% |
| 增量评审 | `--delta .code-review-log.jsonl` | 只取上轮结论与待验收项，不重读全部历史 |
| 批量评分 | `--batch scores.jsonl --log ...` | 多条记录一次跑完，每条输出一行卡 + 汇总 |
| 场景预设 10 套 | `--preset crud/frontend/script/migration/api/mobile/datapipeline/mlexperiment/i18n/infra` | 免维护配置文件秒切权重（开源版无预设机制） |
| 汇报精简模板 | `--template brief` | 结论 + 最弱维度 + 封顶 + 待修，5 行内说完 |
| 周报聚合模板 | `--template weekly --summary log.jsonl` | 按天聚合星级/5 星率/回归/遗留，免手写周报 |
| 趋势图表 | `--report log.jsonl --chart` | 星级分布 + 维度变化 ASCII 图 |
| 配置向导 | `--wizard`（脚本化 `--wizard-answers`） | 交互生成项目配置，权重自动校验 |

Pro 还内置 **Token 效率约定**（默认生效）：连续多轮默认一行卡、评审前先 `--delta` 只评相对变化、圈定对象优先 `--diff` 自动取证、汇报/周报场景默认用模板输出。

> 本节随每次版本更新同步维护，说明当前版本 Pro 与开源版的差异。
