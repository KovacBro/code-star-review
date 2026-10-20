#!/usr/bin/env python3
"""五维加权 → 0-5 星级，含 Gate 封顶、自动风险封顶、历史汇总与取证工具。

模式：code（默认，代码评审）/ qa（日常问答等非代码输出，--mode qa）

示例（Windows 用 python，macOS/Linux 用 python3）：
  python score.py --need 4 --correct 3 --security 4 --maint 3 --verify 2 --gate 3
  python score.py --need 5 --correct 5 --security 5 --maint 4 --verify 5 --json
  python score.py --need 4 --correct 3 --security 4 --maint 3 --verify 2 \
      --log .code-review-log.jsonl --summary .code-review-log.jsonl
  python score.py --summary .code-review-log.jsonl             # 只看汇总，不评分
  python score.py --need 4 --correct 3 --security 4 --maint 3 --verify 2 \
      --diff --run-tests "pytest -q" --log .code-review-log.jsonl   # 自动取证
  python score.py --median "4,3,4,3,2;5,4,4,4,3"               # 多评审取中位+分歧度
  python score.py --report .code-review-log.jsonl              # 跨会话趋势报告
  python score.py --mode qa --need 4 --correct 5 --security 4 --maint 4 --verify 3
  python score.py --need 4 --correct 4 --security 4 --maint 4 --verify 4 \
      --min-stars 4                                            # CI 门禁，低于 4★ 退出码 1
  python score.py --schema                                     # 输出评分卡 JSON Schema
  python score.py --init                                       # 生成 .star-review.yaml 配置模板
  python score.py --need 4 --correct 3 --security 4 --maint 3 --verify 2 --format md --out card.md
"""

import argparse
import fnmatch
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime

VERSION = "1.0.0"
KEYS = ["need", "correct", "security", "maint", "verify"]
DEFAULT_WEIGHTS = {"need": 0.35, "correct": 0.25, "security": 0.15, "maint": 0.15, "verify": 0.10}
MODE_LABELS = {
    "code": {"need": "需求达成", "correct": "正确健壮", "security": "安全副作用",
             "maint": "可维护", "verify": "验证充分"},
    "qa": {"need": "切题准确", "correct": "完整深度", "security": "依据可靠",
           "maint": "结构表达", "verify": "可核验"},
}
THRESHOLDS = [(4.6, 5), (3.9, 4), (3.1, 3), (2.3, 2), (1.3, 1)]
CONFIG_NAMES = [".star-review.yaml", ".star-review.json"]
FUNC_PATTERN = re.compile(r"^\+\s*(?:async\s+)?(?:def|class|function|func|fn)\s+([A-Za-z_]\w*)", re.M)

SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "code-star-review scorecard",
    "type": "object",
    "required": ["version", "mode", "scores", "weighted", "stars"],
    "properties": {
        "version": {"type": "string", "description": "skill 版本"},
        "ts": {"type": "string", "description": "ISO 时间戳"},
        "turn": {"type": ["integer", "null"], "description": "轮次"},
        "mode": {"enum": ["code", "qa"]},
        "strict": {"type": "boolean", "description": "项目配置的严格模式"},
        "scores": {
            "type": "object",
            "required": KEYS,
            "properties": {k: {"type": "number", "minimum": 0, "maximum": 5} for k in KEYS},
        },
        "weighted": {"type": "number", "minimum": 0, "maximum": 5},
        "raw_stars": {"type": "integer", "minimum": 0, "maximum": 5},
        "stars": {"type": "integer", "minimum": 0, "maximum": 5},
        "caps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["cap", "reason"],
                "properties": {"cap": {"type": "integer", "minimum": 0, "maximum": 5},
                               "reason": {"type": "string"}},
            },
        },
        "note": {"type": "string"},
        "verification": {
            "type": "object",
            "description": "--run-tests 的执行结果",
            "properties": {
                "cmd": {"type": "string"},
                "exit_code": {"type": ["integer", "null"]},
                "duration_s": {"type": "number"},
                "tail": {"type": "string"},
            },
        },
        "diff": {
            "type": "object",
            "description": "--diff 的 git 变更取证",
            "properties": {
                "files": {"type": "array", "items": {"type": "object"}},
                "error": {"type": "string"},
            },
        },
        "changed_functions": {"type": "array", "items": {"type": "string"}},
        "fix_items": {"type": "array", "items": {"type": "string"},
                      "description": "下一轮待修项（评分与修复闭环）"},
        "reviewers": {"type": "integer", "minimum": 1},
        "max_spread": {"type": "integer", "minimum": 0, "maximum": 5},
    },
}


def star_bar(stars: int) -> str:
    stars = max(0, min(5, int(stars)))
    return "★" * stars + "☆" * (5 - stars)


def disp_pad(text: str, width: int) -> str:
    """按显示宽度补空格，中文等全角字符按 2 列计，保证终端对齐。"""
    used = sum(2 if ord(ch) > 127 else 1 for ch in text)
    return text + " " * max(0, width - used)


def stars_from_score(score: float) -> int:
    for threshold, stars in THRESHOLDS:
        if score >= threshold:
            return stars
    return 0


def auto_caps(scores: dict, mode: str = "code") -> list:
    """根据维度分自动触发 Gate 上限，防止高危被平均分掩盖。"""
    caps = []
    if mode == "qa":
        if scores["need"] <= 1:
            caps.append((1, "答非所问/严重偏题"))
        if scores["correct"] <= 1:
            caps.append((1, "内容错误或缺关键部分"))
        return caps
    if scores["need"] <= 1:
        caps.append((1, "G1 核心需求未实现或做反"))
    if scores["correct"] <= 1:
        caps.append((1, "G1 主流程不可用"))
    if scores["security"] <= 1:
        caps.append((1, "G1 高危安全问题"))
    elif scores["security"] == 2:
        caps.append((2, "G2 中危安全问题"))
    return caps


def weighted(scores: dict, weights: dict = None) -> float:
    w = weights or DEFAULT_WEIGHTS
    return round(sum(scores[k] * w[k] for k in KEYS), 2)


def build(scores: dict, gate, gate_reason, turn, note, mode: str = "code",
          weights: dict = None, strict: bool = False, extras: dict = None,
          extra_caps: list = None) -> dict:
    w = weights or DEFAULT_WEIGHTS
    base = weighted(scores, w)
    raw = stars_from_score(base)
    caps = auto_caps(scores, mode)
    if gate is not None:
        caps.append((gate, gate_reason or f"G{gate} 人工判定"))
    caps.extend(extra_caps or [])
    cap = min([c[0] for c in caps], default=5)
    final = min(raw, cap)
    result = {
        "version": VERSION,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "turn": turn,
        "mode": mode,
        "strict": strict,
        "weights": w,
        "scores": scores,
        "weighted": base,
        "raw_stars": raw,
        "caps": [{"cap": c, "reason": r} for c, r in caps],
        "stars": final,
        "note": note or "",
    }
    if extras:
        result.update(extras)
    return result


# ---------------------------------------------------------------- 取证：git diff

def _resolve_rename(path: str) -> str:
    """numstat 重命名条目取新路径：`dir/{old => new}.py` → `dir/new.py`。"""
    m = re.match(r"^(.*)\{(.*) => (.*)\}(.*)$", path)
    if m:
        return m.group(1) + m.group(3) + m.group(4)
    if " => " in path:
        return path.split(" => ", 1)[1].strip()
    return path


def parse_numstat(text: str) -> list:
    """解析 `git diff --numstat` 输出 → [{"file", "ins", "del"}]，兼容重命名条目。"""
    files = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            ins, dele, path = parts[0], parts[1], _resolve_rename("\t".join(parts[2:]).strip())
            files.append({"file": path,
                          "ins": int(ins) if ins.isdigit() else None,
                          "del": int(dele) if dele.isdigit() else None})
    return files


def _git(args: list, repo: str = "."):
    try:
        return subprocess.run(["git"] + args, cwd=repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


def run_diff(repo: str = ".") -> dict:
    """git diff HEAD 取证：改动文件清单 + 被改函数名（回归提示）。"""
    proc = _git(["diff", "HEAD", "--numstat"], repo)
    if proc is None or proc.returncode != 0:
        err = ((proc.stderr if proc else "") or "git 不可用").strip()
        return {"error": err.splitlines()[0][:160] if err else "git diff 失败", "files": []}
    files = parse_numstat(proc.stdout)
    funcs = []
    patch = _git(["diff", "HEAD", "-U0"], repo)
    if patch and patch.stdout:
        for m in FUNC_PATTERN.finditer(patch.stdout):
            if m.group(1) not in funcs:
                funcs.append(m.group(1))
    return {"files": files, "changed_functions": funcs[:20]}


def match_cfg_gates(cfg_gates: list, files: list) -> list:
    """项目自定义 Gate：路径命中 glob 模式 → 封顶。"""
    hits = []
    for g in cfg_gates or []:
        pat = str(g.get("path", ""))
        if not pat:
            continue
        if any(fnmatch.fnmatch(str(f.get("file", "")), pat) for f in files or []):
            try:
                cap = int(g.get("cap", 5))
            except (TypeError, ValueError):
                cap = 5
            hits.append((max(0, min(5, cap)), g.get("reason", "项目自定义 Gate")))
    return hits


# ---------------------------------------------------------------- 取证：验证命令

def run_verification(cmd: str, timeout: int = 300) -> dict:
    """执行验证命令，记录退出码、耗时与输出摘要，作为验证维度的硬证据。"""
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        code = proc.returncode
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "exit_code": None, "duration_s": round(time.monotonic() - start, 2),
                "tail": f"超时（>{timeout}s）"}
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    return {"cmd": cmd, "exit_code": code,
            "duration_s": round(time.monotonic() - start, 2),
            "tail": "\n".join(lines[-15:])[:2000]}


# ---------------------------------------------------------------- 多评审取中位

def median_scores(spec: str):
    """解析 "4,3,4,3,2;5,4,4,4,3" → (各维中位分, 评审者信息)。"""
    sets = []
    for part in spec.split(";"):
        vals = [int(x) for x in part.replace(",", " ").split()]
        if len(vals) != 5 or not all(0 <= v <= 5 for v in vals):
            raise ValueError(f"评分组无效：{part!r}（需 5 个 0-5 的整数）")
        sets.append(vals)
    meds = []
    for col in zip(*sets):
        m = statistics.median(col)
        meds.append(int(m) if float(m).is_integer() else float(m))
    scores = dict(zip(KEYS, meds))
    spread = max(max(c) - min(c) for c in zip(*sets))
    return scores, {"reviewers": len(sets), "max_spread": spread}


# ---------------------------------------------------------------- 项目配置

def _parse_scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_yaml_subset(text: str) -> dict:
    """解析 .star-review.yaml 支持的子集：strict、weights（一层嵌套）、gates（dict 列表）。"""
    cfg = {"strict": False, "weights": {}, "gates": []}
    section = None
    cur_gate = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            cur_gate = {}
            cfg["gates"].append(cur_gate)
            section = "gates"
            stripped = stripped[2:].strip()
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                if val.strip():
                    cur_gate[key.strip()] = _parse_scalar(val)
            continue
        indent = len(raw) - len(raw.lstrip())
        key, sep, val = stripped.partition(":")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if indent == 0:
            if val:
                cfg[key] = _parse_scalar(val)
                section = None
            else:
                section = key
                if key == "gates":
                    cur_gate = None
        elif section == "weights":
            cfg["weights"][key] = _parse_scalar(val)
        elif section == "gates" and cur_gate is not None:
            cur_gate[key] = _parse_scalar(val)
    return cfg


def load_config(path: str = None, search_dir: str = "."):
    """加载项目配置；未找到时返回默认值。返回 (cfg, 实际路径或 None)。"""
    if path is None:
        for name in CONFIG_NAMES:
            cand = os.path.join(search_dir, name)
            if os.path.isfile(cand):
                path = cand
                break
    if path is None or not os.path.isfile(path):
        return {"strict": False, "weights": {}, "gates": []}, None
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh) if path.endswith(".json") else parse_yaml_subset(fh.read())
    cfg.setdefault("strict", False)
    cfg.setdefault("weights", {})
    cfg.setdefault("gates", [])
    # 健壮性：gates 段被误写成非列表（如 "[]" 字符串）时回退为空，不让配置崩掉评分
    if not isinstance(cfg["gates"], list):
        cfg["gates"] = []
    return cfg, path


YAML_TEMPLATE = """\
# .star-review.yaml —— code-star-review 项目配置（v{version} 生成）
# 可自定义：
#   strict   严格模式默认开关
#   weights  五维权重（须五维齐全、合计 0.9-1.1，自动归一化）
#   gates    自定义 Gate（路径 glob + 封顶 + 理由），如：
#   - path: "migrations/*"
#     cap: 2
#     reason: "migration 变更须人工复核"
# 不可覆盖：星级阈值与内置 G0-G3 规则（防止把纪律改松）。
strict: false
weights:
  need: 0.35
  correct: 0.25
  security: 0.15
  maint: 0.15
  verify: 0.10
"""


def cmd_init(path: str = ".star-review.yaml") -> int:
    """--init 脚手架：生成项目配置模板，已存在则拒绝覆盖。"""
    if os.path.exists(path):
        print(f"\n  已存在：{path}（不会覆盖；如需重新生成请先删除或手工修改）")
        return 1
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(YAML_TEMPLATE.format(version=VERSION))
    print(f"\n  已生成 {path}（v{VERSION} 模板）")
    print("  下一步：")
    print("  1. 按需修改 weights 与 gates；评分时会自动读取本文件")
    print("  2. 每轮自动评级：把 assets/auto-review-snippet.md 写入 AGENTS.md / CLAUDE.md / .cursorrules")
    print("  3. CI 门禁：--min-stars N（接入示例见 assets/ci-score.yml）")
    return 0


def effective_weights(cfg_weights: dict) -> dict:
    """校验并归一化自定义权重；Gate 规则与星级阈值不接受配置覆盖。"""
    if not cfg_weights:
        return dict(DEFAULT_WEIGHTS)
    missing = [k for k in KEYS if k not in cfg_weights]
    if missing:
        raise ValueError("配置权重缺少维度: " + " ".join(missing))
    w = {k: float(cfg_weights[k]) for k in KEYS}
    total = sum(w.values())
    if total <= 0.9 or total >= 1.1 or any(v < 0 for v in w.values()):
        raise ValueError(f"配置权重无效：合计 {total:.2f}（需五维齐全、非负、合计 0.9-1.1）")
    return {k: round(v / total, 4) for k, v in w.items()}


# ---------------------------------------------------------------- 汇总与报告

def _read_rows(path: str) -> list:
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return None
    return rows


def summarize(path: str) -> str:
    rows = _read_rows(path)
    if rows is None:
        return f"\n  未找到历史文件：{path}"
    if not rows:
        return "\n  历史为空，暂无可汇总数据。"

    n = len(rows)
    avg_stars = sum(r.get("stars", 0) for r in rows) / n
    avg_weighted = sum(r.get("weighted", 0) for r in rows) / n
    dist = {i: 0 for i in range(6)}
    for r in rows:
        dist[int(r.get("stars", 0))] = dist.get(int(r.get("stars", 0)), 0) + 1

    mode = rows[-1].get("mode", "code")
    labels = MODE_LABELS.get(mode, MODE_LABELS["code"])

    dim_avg = {}
    for key in KEYS:
        vals = [r["scores"][key] for r in rows
                if isinstance(r.get("scores"), dict) and key in r["scores"]]
        if vals:
            dim_avg[key] = round(sum(vals) / len(vals), 2)

    weakest = min(dim_avg.items(), key=lambda kv: kv[1]) if dim_avg else None

    trend = ""
    if n >= 4:
        half = n // 2
        before = sum(r.get("stars", 0) for r in rows[:half]) / half
        after = sum(r.get("stars", 0) for r in rows[half:]) / (n - half)
        delta = round(after - before, 2)
        trend = "↑ 上升" if delta > 0.3 else ("↓ 下降" if delta < -0.3 else "→ 持平")
        trend += f"（{delta:+.2f}）"

    lines = ["", f"  共 {n} 轮 ｜ 平均 {avg_stars:.2f}★ ｜ 加权均值 {avg_weighted:.2f}"
             + (f" ｜ 模式 {mode}" if mode != "code" else "")]
    lines.append("  分布：" + "  ".join(f"{i}★×{dist.get(i, 0)}" for i in range(5, -1, -1)))
    if dim_avg:
        lines.append("  维度均值：" + " ".join(f"{labels[k]}{v}" for k, v in dim_avg.items()))
    if weakest:
        lines.append(f"  最弱维度：{labels[weakest[0]]}（{weakest[1]}/5）——优先补这项")
    if trend:
        lines.append(f"  趋势：{trend}")

    pending = next((r.get("fix_items") for r in reversed(rows)
                    if r.get("fix_items")), None)
    if pending:
        lines.append("  上轮遗留待修：" + "；".join(pending))
    return "\n".join(lines)


def expand_report_paths(paths: list) -> list:
    """--report 支持目录：自动展开目录下全部 .jsonl 文件。"""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(os.path.join(p, n) for n in os.listdir(p)
                              if n.endswith(".jsonl")))
        else:
            out.append(p)
    return out


def report(paths: list) -> str:
    """跨会话趋势报告：5 星率、维度变化、回归点、遗留待修。"""
    rows = []
    for p in paths:
        sub = _read_rows(p)
        if sub:
            rows.extend(sub)
    if not rows:
        return "\n  无可汇总数据。"

    n = len(rows)
    stars = [int(r.get("stars", 0)) for r in rows]
    avg = sum(stars) / n
    five_rate = sum(1 for s in stars if s == 5) / n
    mode = rows[-1].get("mode", "code")
    labels = MODE_LABELS.get(mode, MODE_LABELS["code"])

    def dim_mean(sub_rows, key):
        vals = [r["scores"][key] for r in sub_rows
                if isinstance(r.get("scores"), dict) and key in r["scores"]]
        return round(sum(vals) / len(vals), 2) if vals else None

    lines = ["", f"  趋势报告 ｜ 共 {n} 轮 ｜ 平均 {avg:.2f}★ ｜ 5 星率 {five_rate:.0%}"]
    lines.append("  分布：" + "  ".join(f"{i}★×{stars.count(i)}" for i in range(5, -1, -1)))

    if n >= 4:
        half = n // 2
        lines.append("  维度变化（前半 → 后半）：")
        for key in KEYS:
            before, after = dim_mean(rows[:half], key), dim_mean(rows[half:], key)
            if before is None or after is None:
                continue
            delta = round(after - before, 2)
            mark = "↑" if delta > 0.3 else ("↓" if delta < -0.3 else "→")
            lines.append(f"    {labels[key]}：{before} → {after} {mark}")
        weak_now = min(KEYS, key=lambda k: dim_mean(rows[half:], k) or 5)
        lines.append(f"  当前最弱维度：{labels[weak_now]}（{dim_mean(rows[half:], weak_now)}/5）"
                     "——下一轮优先补")

    regressions = []
    for prev, cur in zip(rows, rows[1:]):
        drop = int(prev.get("stars", 0)) - int(cur.get("stars", 0))
        if drop >= 2:
            where = f"第 {cur.get('turn')} 轮" if cur.get("turn") else cur.get("ts", "?")
            note = cur.get("note") or ""
            suffix = f"（{note}）" if note else ""
            regressions.append(f"{where} {prev.get('stars')}★→{cur.get('stars')}★{suffix}")
    if regressions:
        lines.append("  回归点（星级骤降 ≥2）：" + "；".join(regressions[:5]))
    else:
        lines.append("  回归点：无")

    pending = next((r.get("fix_items") for r in reversed(rows) if r.get("fix_items")), None)
    if pending:
        lines.append("  遗留待修（最近一轮）：" + "；".join(pending))
    return "\n".join(lines)


# ---------------------------------------------------------------- 输出

def render(result: dict) -> str:
    labels = MODE_LABELS.get(result.get("mode", "code"), MODE_LABELS["code"])
    weights = result.get("weights") or DEFAULT_WEIGHTS
    scores = result["scores"]
    lines = [""]
    for key in KEYS:
        lines.append(
            f"  {disp_pad(labels[key], 10)} {scores[key]}/5  × {int(weights[key]*100):>2}%"
        )
    lines.append(f"\n  加权分：{result['weighted']:.2f}  →  原始 {star_bar(result['raw_stars'])} {result['raw_stars']}/5")
    for cap in result["caps"]:
        lines.append(f"  封顶：{cap['reason']} → 上限 {cap['cap']}★")
    lines.append(f"\n  最终评级：{star_bar(result['stars'])}  {result['stars']}/5")
    if result.get("mode") == "qa":
        lines.append("  模式：问答评审")
    if result.get("strict"):
        lines.append("  严格模式：已启用（项目配置）")
    if result.get("turn") is not None:
        lines.append(f"  轮次：第 {result['turn']} 轮")

    diff = result.get("diff") or {}
    files = diff.get("files") or []
    if diff.get("error"):
        lines.append(f"  diff：获取失败（{diff['error']}）")
    elif files:
        total_ins = sum(f["ins"] or 0 for f in files)
        total_del = sum(f["del"] or 0 for f in files)
        lines.append(f"  diff：{len(files)} 个文件，+{total_ins}/-{total_del}")
        for f in files[:10]:
            lines.append(f"    - {f['file']} (+{f['ins'] or 0}/-{f['del'] or 0})")
    if result.get("changed_functions"):
        lines.append("  回归提示：以下函数被修改，请检查调用方 → "
                     + ", ".join(result["changed_functions"]))

    ver = result.get("verification")
    if ver:
        code_str = ver["exit_code"] if ver["exit_code"] is not None else "超时"
        lines.append(f"  验证命令：{ver['cmd']} → 退出码 {code_str}，耗时 {ver['duration_s']}s")
        tail_lines = (ver.get("tail") or "").splitlines()
        for ln in tail_lines[-3:]:
            lines.append(f"    | {ln}")
    if result.get("reviewers"):
        lines.append(f"  多评审：{result['reviewers']} 份取中位，最大分歧 {result['max_spread']} 分")
    if result.get("fix_items"):
        lines.append("  下轮待修：" + "；".join(result["fix_items"]))
    if result.get("note"):
        lines.append(f"  备注：{result['note']}")
    return "\n".join(lines)


def render_markdown(result: dict) -> str:
    """--format md：输出 markdown 评分卡，可直接贴进 PR/文档。"""
    labels = MODE_LABELS.get(result.get("mode", "code"), MODE_LABELS["code"])
    weights = result.get("weights") or DEFAULT_WEIGHTS
    scores = result["scores"]
    mode = result.get("mode", "code")
    title = "问答评级" if mode == "qa" else "代码评级"
    lines = [f"### {title} — {star_bar(result['stars'])} {result['stars']}/5", ""]
    if result.get("turn") is not None:
        lines[0] = f"### {title} · 第 {result['turn']} 轮 — {star_bar(result['stars'])} {result['stars']}/5"
    lines.append("| 维度 | 得分 | 权重 |")
    lines.append("| --- | --- | --- |")
    for key in KEYS:
        lines.append(f"| {labels[key]} | {scores[key]}/5 | {int(weights[key]*100)}% |")
    lines.append(f"| **加权** | **{result['weighted']:.2f}** | "
                 f"原始 {result['raw_stars']}★ |")
    lines.append("")
    for cap in result["caps"]:
        lines.append(f"- 封顶：{cap['reason']} → 上限 {cap['cap']}★")
    tags = []
    if mode == "qa":
        tags.append("问答模式")
    if result.get("strict"):
        tags.append("严格模式")
    if tags:
        lines.append(f"- 模式：{'、'.join(tags)}")
    diff = result.get("diff") or {}
    files = diff.get("files") or []
    if diff.get("error"):
        lines.append(f"- diff：获取失败（{diff['error']}）")
    elif files:
        total_ins = sum(f["ins"] or 0 for f in files)
        total_del = sum(f["del"] or 0 for f in files)
        lines.append(f"- diff：{len(files)} 个文件，+{total_ins}/-{total_del}")
    if result.get("changed_functions"):
        lines.append("- 回归提示：被改函数请查调用方 → " + ", ".join(result["changed_functions"]))
    ver = result.get("verification")
    if ver:
        code_str = ver["exit_code"] if ver["exit_code"] is not None else "超时"
        lines.append(f"- 验证：`{ver['cmd']}` → 退出码 {code_str}，{ver['duration_s']}s")
    if result.get("reviewers"):
        lines.append(f"- 多评审：{result['reviewers']} 份取中位，最大分歧 {result['max_spread']} 分")
    if result.get("fix_items"):
        lines.append("- 下轮待修：" + "；".join(result["fix_items"]))
    if result.get("note"):
        lines.append(f"- 备注：{result['note']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=f"代码/问答五维评分 → 0-5 星级（含 Gate 封顶）v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for key in KEYS:
        parser.add_argument(f"--{key}", type=int, choices=range(0, 6), metavar="0-5",
                            help="维度分（权重可被项目配置覆盖）")
    parser.add_argument("--mode", choices=["code", "qa"], default="code",
                        help="code=代码评审（默认），qa=日常问答等非代码输出")
    parser.add_argument("--gate", type=int, choices=range(0, 6), help="人工 Gate 上限（0-5）")
    parser.add_argument("--gate-reason", default="", help="Gate 判定理由")
    parser.add_argument("--turn", type=int, help="轮次编号，用于日志")
    parser.add_argument("--note", default="", help="一句话结论，写入日志")
    parser.add_argument("--median", help='多评审取中位，如 "4,3,4,3,2;5,4,4,4,3"')
    parser.add_argument("--diff", nargs="?", const=".", metavar="REPO",
                        help="运行 git diff HEAD 取证（可选仓库路径，默认当前目录）")
    parser.add_argument("--run-tests", metavar="CMD",
                        help="执行验证命令，把退出码/耗时/输出摘要写入记录")
    parser.add_argument("--config", help="项目配置文件（默认自动查找 .star-review.yaml/.json）")
    parser.add_argument("--min-stars", type=int, choices=range(0, 6),
                        help="CI 门禁：最终星级低于该值时以退出码 1 结束")
    parser.add_argument("--fix", action="append", default=[], metavar="ITEM",
                        help="下一轮待修项，可重复传入（评分与修复闭环）")
    parser.add_argument("--log", help="追加记录到 JSONL 文件")
    parser.add_argument("--summary", help="汇总指定 JSONL 文件")
    parser.add_argument("--report", nargs="+", metavar="JSONL",
                        help="跨会话趋势报告（可传多个文件）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（等价 --format json，向后兼容）")
    parser.add_argument("--format", choices=["text", "md", "json"], default=None,
                        help="输出格式：text=终端卡（默认），md=markdown 评分卡，json=JSON")
    parser.add_argument("--out", metavar="FILE", help="把评分卡输出写入文件（配合 --format 使用）")
    parser.add_argument("--init", action="store_true",
                        help="在当前目录生成 .star-review.yaml 配置模板（已存在则拒绝覆盖）")
    parser.add_argument("--schema", action="store_true", help="输出评分卡 JSON Schema（供 CI/机器人消费）")
    parser.add_argument("--version", action="store_true", help="输出版本号")
    args = parser.parse_args(argv)

    if args.version:
        print(f"code-star-review {VERSION}")
        return 0
    if args.schema:
        print(json.dumps(SCHEMA, ensure_ascii=False, indent=2))
        return 0
    if args.init:
        return cmd_init()

    # --json（旧参数）向后兼容为 --format json
    fmt = "json" if args.json else (args.format or "text")

    try:
        cfg, cfg_path = load_config(args.config)
        weights = effective_weights(cfg.get("weights"))
    except (ValueError, json.JSONDecodeError) as exc:
        parser.error(f"配置加载失败：{exc}")
    strict = bool(cfg.get("strict"))

    provided = [k for k in KEYS if getattr(args, k) is not None]
    reviewer_info = None

    if not provided and not args.median:
        output = []
        if args.summary:
            output.append(summarize(args.summary))
        if args.report:
            output.append(report(expand_report_paths(args.report)))
        if output:
            print("\n".join(output))
            return 0
        parser.error("需要提供五个维度分，或使用 --summary/--report 查看历史，或 --median 多评审")

    if args.median:
        try:
            scores, reviewer_info = median_scores(args.median)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        missing = [k for k in KEYS if getattr(args, k) is None]
        if missing:
            parser.error("缺少维度分: " + " ".join(f"--{k}" for k in missing))
        scores = {key: getattr(args, key) for key in KEYS}

    extras = {}
    if cfg_path:
        extras["config"] = cfg_path
    cfg_caps = []
    if args.diff:
        diff_info = run_diff(args.diff)
        extras["diff"] = diff_info
        if diff_info.get("changed_functions"):
            extras["changed_functions"] = diff_info["changed_functions"]
        cfg_caps = match_cfg_gates(cfg.get("gates"), diff_info.get("files") or [])
    if args.run_tests:
        extras["verification"] = run_verification(args.run_tests)
    if reviewer_info:
        extras.update(reviewer_info)
    if args.fix:
        extras["fix_items"] = args.fix

    result = build(scores, args.gate, args.gate_reason, args.turn, args.note,
                   mode=args.mode, weights=weights, strict=strict,
                   extras=extras or None, extra_caps=cfg_caps)

    if args.log:
        with open(args.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")

    blocks = []
    if fmt == "json":
        blocks.append(json.dumps(result, ensure_ascii=False, indent=2))
    elif fmt == "md":
        blocks.append(render_markdown(result))
    else:
        blocks.append(render(result))
    if args.summary:
        blocks.append(summarize(args.summary))
    if args.report:
        blocks.append(report(args.report))
    output = "\n".join(blocks)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(output + "\n")
        print(f"  已写入 {args.out}（--format {fmt}）")
    else:
        print(output)

    if args.min_stars is not None and result["stars"] < args.min_stars:
        print(f"\n  门禁失败：最终 {result['stars']}★ 低于要求 {args.min_stars}★", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
