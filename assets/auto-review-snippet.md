# 逐轮自动评级规则片段

Skill 只在被调用时生效。要让"每一轮都自动评"，把下面的规则块粘到项目根目录的规则文件里（`AGENTS.md`、`CLAUDE.md`、`.cursorrules`、`.github/copilot-instructions.md` 均可），新会话即生效。

---

## 规则块（直接复制）

```markdown
## 逐轮代码评级（使用 code-star-review skill）

适用于本项目所有产生或修改代码的回复。

每轮结束时：
1. 本轮有代码变更 → 按 code-star-review 的规则评 0-5 星。
2. 默认在回复末尾追加一行，不展开：
   `代码评级：★★★★☆ 4/5 — <一句话结论>；P2: <最该修的一项（file:line）>`
3. 本轮无代码变更 → 只写：`本轮无代码产出，不评分。`
4. 用户说"展开评分" → 输出标准评分卡。
5. 用户说"严格模式" → 用严格卡，列阻断项与验证清单。

硬性约束：
- 5 星须同时满足：验收点全部达成、异常与边界完备、无 P0-P2、有可核验的验证证据、改动最小。
- 没看到测试或真实运行输出 → 验证维度 ≤2，不得给 5 星。
- 安全维度 ≤1（高危）→ 直接封顶 1 星；伪造测试/运行结果 → 直接 0 星。
- 每个扣分必须指到 file:line 或具体行为，指不出不扣。
- 星级只看本轮，不因上一轮表现加减分。
```

---

## 会话内临时开启（不改文件）

直接对 AI 说：

> 从这一轮开始，每轮结束给代码评 0-5 星，一行就行；我说"展开"你再给详细评分卡。

AI 应确认并在后续每轮遵守。会话结束即失效。

---

## 留痕与趋势

```bash
# 每轮追加一条，同时看汇总。
# 先把下面的 score.py 路径替换为本 skill 的实际安装路径，例如：
#   Windows:     python "e:\skills\code-star-review\scripts\score.py"
#   macOS/Linux: python3 /path/to/code-star-review/scripts/score.py
python scripts/score.py --need 4 --correct 3 --security 4 --maint 3 --verify 2 \
  --turn 3 --log .code-review-log.jsonl --summary .code-review-log.jsonl
```

`.code-review-log.jsonl` 建议加进 `.gitignore`（本地质量数据，不必入库）；团队想共享趋势时再提交。

汇总会给出：总轮次、平均星级、星级分布、各维度均值、最弱维度、前后半程趋势。

---

## 关闭

- 临时：说"这轮不用评分"。
- 长期：删除规则块，或在其后加一行 `<!-- code-star-review: disabled -->` 并让 AI 忽略本节。
