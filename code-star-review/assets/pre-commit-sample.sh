#!/bin/sh
# pre-commit 门禁示例：提交前对本轮改动自动评分，低于阈值拦截提交。
# 安装：复制本文件为 .git/hooks/pre-commit 并赋予执行权限（chmod +x）。
# 注意：pre-commit 时改动尚未提交，git diff HEAD 只能看到已暂存内容；
#      若要评已暂存的改动，可在 score.py 调用中改用 --gate 由 AI 预先评好写入文件，
#      或改在 CI 中用 --diff（提交后视角）做门禁。下方使用 CI 推荐方式的本地等价物。

# 五维分数由 AI 评审后写入 .star-review-last.json，或在此硬编码最近一轮评分：
NEED=${NEED:-3}
CORRECT=${CORRECT:-3}
SECURITY=${SECURITY:-4}
MAINT=${MAINT:-3}
VERIFY=${VERIFY:-2}
MIN_STARS=${MIN_STARS:-4}

SKILL_DIR="${CODE_STAR_REVIEW_DIR:-/path/to/code-star-review}"

python "$SKILL_DIR/scripts/score.py" \
  --need "$NEED" --correct "$CORRECT" --security "$SECURITY" \
  --maint "$MAINT" --verify "$VERIFY" \
  --min-stars "$MIN_STARS" \
  --note "pre-commit 门禁"

exit $?
