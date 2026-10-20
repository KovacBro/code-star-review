# Changelog

## 0.9.2（2026-10-20）

### score.py 新功能

- **取证自动化**：`--diff [REPO]` 运行 `git diff HEAD`，输出改动文件清单与增删行数；同时粗检被改函数名（def/class/function/func/fn），生成"请检查调用方"回归提示。
- **验证联动**：`--run-tests CMD` 执行验证命令，把退出码、耗时、输出摘要写入评分记录，作为"验证充分"维度的硬证据。
- **多评审一致性**：`--median "4,3,4,3,2;5,4,4,4,3"` 多份独立评分取各维中位，输出评审者数量与最大分歧。
- **跨会话趋势报告**：`--report <jsonl...>` 输出 5 星率、维度前后半变化、回归点（星级骤降 ≥2）、遗留待修项；支持多文件合并。
- **项目配置**：自动查找 `.star-review.yaml` / `.star-review.json`（或 `--config` 指定），支持自定义权重（强制五维齐全、合计 0.9-1.1、自动归一化）、自定义 Gate（路径 glob + 封顶 + 理由）、严格模式开关。星级阈值与内置 G0-G3 不可覆盖。
- **CI 门禁**：`--min-stars N` 最终星级低于 N 时以退出码 1 结束，用于 pre-commit / 流水线拦截。
- **评分与修复闭环**：`--fix ITEM`（可重复）登记下一轮待修项，`--summary` 自动提示"上轮遗留待修"。
- **问答模式**：`--mode qa`，维度切换为切题准确/完整深度/依据可靠/结构表达/可核验，支持对日常问答等非代码输出评分；切题 ≤1 封顶 1 星。
- **结构化输出**：`--schema` 输出评分卡 JSON Schema（draft-07），供 CI、机器人、看板消费；`--version` 输出版本号。
- 评分记录新增 `version`、`mode`、`strict`、`weights` 等字段。

### 文档与资产

- `SKILL.md`：新增 §9 问答模式、§10 项目配置与 CI 门禁；纪律第 7 条改为"非代码默认不评，明确要求时切问答模式"。
- `references/qa-rubric.md`（新增）：问答模式五维完整锚点与特有纪律。
- `references/calibration.md`：新增案例 G（TS/React 组件 4★）、H（SQL 迁移 Gate 封顶 2★）、I（Dockerfile 3★）；快速对照表补非代码速判。
- `assets/star-review.example.yaml`：项目配置示例。
- `assets/pre-commit-sample.sh` / `assets/ci-score.yml`：git hook 与 CI 门禁接入示例。

### 测试

- 回归测试从 15 例扩展到 49 例，覆盖阈值边界、Gate/auto_caps（code+qa）、numstat 解析、自定义 Gate 匹配、多评审中位、配置解析与权重校验、汇总/报告、门禁退出码、fix 闭环、schema/version 输出。

## 0.9.1（2026-10-20）

- 修复评估报告 O1-O8：Windows/macOS 命令双写法、`--summary` 仅汇总模式（不评分不写日志）、diff 获取指引、扣分参考校准声明、新增 `test_score.py`（15 例）、description 触发词扩充、占位符路径说明、终端显示宽度对齐。
- 新增 `EVALUATION.md` 评估与优化计划（含修复记录）。

## 0.9.0

- 首版：五维加权 + Gate 封顶 + 证据制评分卡 + `score.py` + 校准案例 + 逐轮自动评级片段。
