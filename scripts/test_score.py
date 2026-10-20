#!/usr/bin/env python3
"""score.py 的回归测试（纯标准库 unittest，无第三方依赖）。

运行（Windows 用 python，macOS/Linux 用 python3）：
  python scripts/test_score.py
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import score


def full_scores(**overrides):
    base = {"need": 5, "correct": 5, "security": 5, "maint": 5, "verify": 5}
    base.update(overrides)
    return base


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def sample_row(stars=3, weighted=3.4, **scores):
    row = {"stars": stars, "weighted": weighted,
           "scores": {"need": 4, "correct": 3, "security": 4, "maint": 3, "verify": 2}}
    if scores:
        row["scores"].update(scores)
    return row


# ---------------------------------------------------------------- 基础机制

class StarMappingTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        cases = [
            (4.59, 4), (4.60, 5),
            (3.89, 3), (3.90, 4),
            (3.09, 2), (3.10, 3),
            (2.29, 1), (2.30, 2),
            (1.29, 0), (1.30, 1),
            (0.0, 0), (5.0, 5),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(score.stars_from_score(value), expected)


class WeightedTests(unittest.TestCase):
    def test_known_value(self):
        got = score.weighted(full_scores(need=4, correct=3, security=4, maint=3, verify=2))
        self.assertEqual(got, 3.40)

    def test_custom_weights(self):
        w = {"need": 0.2, "correct": 0.2, "security": 0.2, "maint": 0.2, "verify": 0.2}
        got = score.weighted(full_scores(need=4, correct=3, security=4, maint=3, verify=2), w)
        self.assertEqual(got, 3.20)


class AutoCapsTests(unittest.TestCase):
    def test_security_1_caps_at_1(self):
        caps = score.auto_caps(full_scores(security=1))
        self.assertEqual(caps[0][0], 1)

    def test_security_2_caps_at_2(self):
        caps = score.auto_caps(full_scores(security=2))
        self.assertEqual(caps[0][0], 2)

    def test_no_caps_when_all_high(self):
        self.assertEqual(score.auto_caps(full_scores()), [])

    def test_qa_mode_off_topic_caps(self):
        caps = score.auto_caps(full_scores(need=1), mode="qa")
        self.assertEqual(caps[0][0], 1)

    def test_qa_mode_ignores_security_cap(self):
        self.assertEqual(score.auto_caps(full_scores(security=1), mode="qa"), [])


class BuildTests(unittest.TestCase):
    def test_gate_0_not_swallowed(self):
        result = score.build(full_scores(), 0, "G0 测试", None, "")
        self.assertEqual(result["stars"], 0)
        self.assertIn({"cap": 0, "reason": "G0 测试"}, result["caps"])

    def test_manual_gate_overrides_high_score(self):
        result = score.build(full_scores(), 3, "", None, "")
        self.assertEqual(result["stars"], 3)

    def test_auto_cap_beats_weighted(self):
        result = score.build(full_scores(security=1), None, None, None, "")
        self.assertEqual(result["stars"], 1)

    def test_extra_caps_applied(self):
        result = score.build(full_scores(), None, None, None, "",
                             extra_caps=[(2, "项目 Gate：migration 保护")])
        self.assertEqual(result["stars"], 2)

    def test_record_metadata(self):
        result = score.build(full_scores(verify=4), None, None, 7, "ok",
                             mode="qa", strict=True, extras={"fix_items": ["补校验"]})
        self.assertEqual(result["version"], score.VERSION)
        self.assertEqual(result["mode"], "qa")
        self.assertTrue(result["strict"])
        self.assertEqual(result["fix_items"], ["补校验"])

    def test_effective_weights_recorded(self):
        w = {"need": 0.30, "correct": 0.25, "security": 0.15, "maint": 0.15, "verify": 0.15}
        result = score.build(full_scores(), None, None, None, "", weights=w)
        self.assertEqual(result["weights"], w)


# ---------------------------------------------------------------- 取证

class NumstatTests(unittest.TestCase):
    def test_parse_normal(self):
        text = "10\t2\tsrc/a.py\n3\t0\tsrc/b.ts\n"
        files = score.parse_numstat(text)
        self.assertEqual(files[0], {"file": "src/a.py", "ins": 10, "del": 2})
        self.assertEqual(len(files), 2)

    def test_parse_binary(self):
        files = score.parse_numstat("Bin\t-\timg.png\n")
        self.assertEqual(files[0]["ins"], None)
        self.assertEqual(files[0]["del"], None)

    def test_parse_rename(self):
        files = score.parse_numstat("4\t1\tsrc/{old.py => new.py}\n")
        self.assertEqual(files[0]["file"], "src/new.py")

    def test_parse_rename_whole(self):
        files = score.parse_numstat("2\t0\ta.py => b.py\n")
        self.assertEqual(files[0]["file"], "b.py")


class ExpandReportPathsTests(unittest.TestCase):
    def test_directory_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_jsonl(os.path.join(tmp, "a.jsonl"), [sample_row(3)])
            write_jsonl(os.path.join(tmp, "b.jsonl"), [sample_row(4)])
            write_jsonl(os.path.join(tmp, "ignore.txt"), [])
            got = score.expand_report_paths([tmp])
            self.assertEqual(len(got), 2)
            self.assertTrue(got[0].endswith("a.jsonl"))

    def test_plain_path_passthrough(self):
        self.assertEqual(score.expand_report_paths(["x.jsonl"]), ["x.jsonl"])


class CfgGateTests(unittest.TestCase):
    def test_glob_match(self):
        gates = [{"path": "migrations/*", "cap": 2, "reason": "migration 保护"}]
        files = [{"file": "migrations/003_drop.sql", "ins": 5, "del": 1}]
        hits = score.match_cfg_gates(gates, files)
        self.assertEqual(hits, [(2, "migration 保护")])

    def test_no_match(self):
        gates = [{"path": "migrations/*", "cap": 2}]
        hits = score.match_cfg_gates(gates, [{"file": "src/a.py", "ins": 1, "del": 1}])
        self.assertEqual(hits, [])

    def test_invalid_cap_clamped(self):
        gates = [{"path": "*", "cap": 99}]
        self.assertEqual(score.match_cfg_gates(gates, [{"file": "x"}]), [(5, "项目自定义 Gate")])


# ---------------------------------------------------------------- 多评审

class MedianTests(unittest.TestCase):
    def test_odd_reviewers(self):
        scores, info = score.median_scores("4,3,4,3,2;5,4,4,4,3;3,2,4,3,2")
        self.assertEqual(scores["need"], 4)
        self.assertEqual(info["reviewers"], 3)

    def test_even_reviewers_half_median(self):
        scores, info = score.median_scores("5,5,5,5,5;3,3,3,3,3")
        self.assertEqual(scores["correct"], 4)
        self.assertEqual(info["max_spread"], 2)

    def test_invalid_group_rejected(self):
        with self.assertRaises(ValueError):
            score.median_scores("4,3,4,3")       # 只有 4 个
        with self.assertRaises(ValueError):
            score.median_scores("4,3,4,3,9")     # 超范围


# ---------------------------------------------------------------- 项目配置

class ConfigTests(unittest.TestCase):
    YAML_TEXT = """\
# 项目级评分配置
strict: true
weights:
  need: 0.30
  correct: 0.25
  security: 0.15
  maint: 0.15
  verify: 0.15
gates:
  - path: "migrations/*"
    cap: 2
    reason: "migration 变更须人工复核"
"""

    def test_parse_yaml_subset(self):
        cfg = score.parse_yaml_subset(self.YAML_TEXT)
        self.assertTrue(cfg["strict"])
        self.assertAlmostEqual(sum(cfg["weights"].values()), 1.0, places=6)
        self.assertEqual(cfg["weights"]["need"], 0.30)
        self.assertEqual(cfg["gates"][0]["cap"], 2)
        self.assertEqual(cfg["gates"][0]["reason"], "migration 变更须人工复核")

    def test_load_config_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".star-review.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"strict": True, "weights": {}, "gates": []}, fh)
            cfg, found = score.load_config(path)
            self.assertTrue(cfg["strict"])
            self.assertEqual(found, path)

    def test_load_config_missing_returns_defaults(self):
        cfg, found = score.load_config(os.path.join("no", "such.yaml"))
        self.assertEqual(cfg["weights"], {})
        self.assertIsNone(found)

    def test_effective_weights_normalize(self):
        w = score.effective_weights({"need": 0.30, "correct": 0.20, "security": 0.20,
                                     "maint": 0.20, "verify": 0.10})
        self.assertAlmostEqual(sum(w.values()), 1.0, places=4)
        self.assertEqual(w["need"], 0.30)

    def test_effective_weights_rejects_partial(self):
        with self.assertRaises(ValueError):
            score.effective_weights({"need": 0.5, "correct": 0.5})

    def test_effective_weights_rejects_bad_total(self):
        with self.assertRaises(ValueError):
            score.effective_weights({"need": 0.5, "correct": 0.2, "security": 0.1,
                                     "maint": 0.1, "verify": 0.5})


# ---------------------------------------------------------------- 汇总与报告

class SummarizeTests(unittest.TestCase):
    def test_missing_file(self):
        out = score.summarize(os.path.join("no", "such", "file.jsonl"))
        self.assertIn("未找到历史文件", out)

    def test_bad_lines_skipped_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(sample_row(3), ensure_ascii=False) + "\n")
                fh.write("not-json\n\n")
                fh.write(json.dumps(sample_row(4), ensure_ascii=False) + "\n")
            out = score.summarize(path)
            self.assertIn("共 2 轮", out)
            self.assertIn("最弱维度", out)

    def test_trend_requires_four_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "log.jsonl"),
                               [sample_row(s) for s in (1, 2, 4, 5)])
            self.assertIn("趋势", score.summarize(path))

    def test_pending_fix_items_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            row = sample_row(3)
            row["fix_items"] = ["补参数校验"]
            write_jsonl(path, [row])
            self.assertIn("补参数校验", score.summarize(path))


class ReportTests(unittest.TestCase):
    def test_empty(self):
        self.assertIn("无可汇总数据", score.report(["no/such.jsonl"]))

    def test_five_star_rate_and_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            r1, r2, r3 = sample_row(5), sample_row(5), sample_row(2)
            r3["turn"], r3["note"] = 3, "回归：吞异常"
            write_jsonl(path, [r1, r2, r3])
            out = score.report([path])
            self.assertIn("5 星率 67%", out)
            self.assertIn("回归点", out)
            self.assertIn("第 3 轮 5★→2★（回归：吞异常）", out)

    def test_no_regression_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "log.jsonl"),
                               [sample_row(3), sample_row(4)])
            self.assertIn("回归点：无", score.report([path]))

    def test_multi_file_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = write_jsonl(os.path.join(tmp, "a.jsonl"), [sample_row(5)])
            p2 = write_jsonl(os.path.join(tmp, "b.jsonl"), [sample_row(4)])
            self.assertIn("共 2 轮", score.report([p1, p2]))


# ---------------------------------------------------------------- CLI

class MainTests(unittest.TestCase):
    def test_summary_only_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "log.jsonl"), [sample_row(3)])
            before = os.path.getsize(path)
            buf = StringIO()
            with redirect_stdout(buf):
                code = score.main(["--summary", path])
            self.assertEqual(code, 0)
            self.assertIn("共 1 轮", buf.getvalue())
            self.assertEqual(os.path.getsize(path), before)  # 未追加任何记录

    def test_report_only_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_jsonl(os.path.join(tmp, "log.jsonl"), [sample_row(3)])
            buf = StringIO()
            with redirect_stdout(buf):
                code = score.main(["--report", path])
            self.assertEqual(code, 0)
            self.assertIn("趋势报告", buf.getvalue())

    def test_missing_scores_errors(self):
        with self.assertRaises(SystemExit) as ctx:
            score.main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_partial_scores_errors(self):
        with self.assertRaises(SystemExit):
            score.main(["--need", "4", "--correct", "3"])

    def test_normal_scoring_writes_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            with redirect_stdout(StringIO()):
                code = score.main(["--need", "4", "--correct", "3", "--security", "4",
                                   "--maint", "3", "--verify", "2", "--log", path])
            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as fh:
                row = json.loads(fh.readline())
            self.assertEqual(row["stars"], 3)
            self.assertEqual(row["weighted"], 3.40)
            self.assertEqual(row["version"], score.VERSION)

    def test_qa_mode(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(["--mode", "qa", "--need", "4", "--correct", "5",
                               "--security", "4", "--maint", "4", "--verify", "3"])
        self.assertEqual(code, 0)
        self.assertIn("问答评审", buf.getvalue())
        self.assertIn("切题准确", buf.getvalue())

    def test_min_stars_gate_pass(self):
        with redirect_stdout(StringIO()):
            code = score.main(["--need", "5", "--correct", "5", "--security", "5",
                               "--maint", "5", "--verify", "5", "--min-stars", "4"])
        self.assertEqual(code, 0)

    def test_min_stars_gate_fail(self):
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            code = score.main(["--need", "4", "--correct", "3", "--security", "4",
                               "--maint", "3", "--verify", "2", "--min-stars", "4"])
        self.assertEqual(code, 1)
        self.assertIn("门禁失败", err.getvalue())

    def test_median_mode(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(["--median", "5,5,5,5,5;3,3,3,3,3"])
        self.assertEqual(code, 0)
        self.assertIn("多评审", buf.getvalue())

    def test_fix_items_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            with redirect_stdout(StringIO()):
                score.main(["--need", "4", "--correct", "4", "--security", "4",
                            "--maint", "4", "--verify", "4",
                            "--fix", "补校验", "--fix", "补测试", "--log", path])
            with open(path, encoding="utf-8") as fh:
                row = json.loads(fh.readline())
            self.assertEqual(row["fix_items"], ["补校验", "补测试"])

    def test_config_with_custom_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, ".star-review.json")
            with open(cfg_path, "w", encoding="utf-8") as fh:
                json.dump({"strict": True, "weights": {},
                           "gates": [{"path": "migrations/*", "cap": 2,
                                      "reason": "migration 保护"}]}, fh)
            # 不经 git，直接验证 match 逻辑与配置串联：命中 migrations 文件时封顶
            hits = score.match_cfg_gates(
                json.load(open(cfg_path, encoding="utf-8"))["gates"],
                [{"file": "migrations/003.sql", "ins": 1, "del": 1}])
            self.assertEqual(hits, [(2, "migration 保护")])

    def test_schema_output(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(["--schema"])
        self.assertEqual(code, 0)
        schema = json.loads(buf.getvalue())
        self.assertIn("properties", schema)
        self.assertIn("stars", schema["properties"])

    def test_version_output(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(score.VERSION, buf.getvalue())

    def test_run_tests_records_verification(self):
        cmd = f'"{sys.executable}" -c "print(\'ok\')"'
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(["--need", "4", "--correct", "4", "--security", "4",
                               "--maint", "4", "--verify", "4", "--run-tests", cmd])
        self.assertEqual(code, 0)
        self.assertIn("验证命令", buf.getvalue())


# ---------------------------------------------------------------- v1.0 基础边界

class UtilTests(unittest.TestCase):
    def test_star_bar_bounds(self):
        self.assertEqual(score.star_bar(-3), "☆"*5)
        self.assertEqual(score.star_bar(9), "★"*5)
        self.assertEqual(score.star_bar(3), "★★★☆☆")

    def test_disp_pad_fullwidth_alignment(self):
        padded = score.disp_pad("需求达成", 10)
        self.assertEqual(len(padded), 6)  # 4 个汉字占 8 列，补 2 个空格 → 字符串长 6
        self.assertTrue(padded.startswith("需求达成"))

    def test_version_string_is_1_0(self):
        self.assertTrue(score.VERSION.startswith("1.0"))


class MedianEdgeTests(unittest.TestCase):
    def test_single_reviewer_passthrough(self):
        scores, info = score.median_scores("2,3,4,5,1")
        self.assertEqual(scores, {"need": 2, "correct": 3, "security": 4,
                                  "maint": 5, "verify": 1})
        self.assertEqual(info, {"reviewers": 1, "max_spread": 0})

    def test_spaces_as_separator(self):
        scores, _ = score.median_scores("4 3 4 3 2")
        self.assertEqual(scores["need"], 4)


class YamlEdgeTests(unittest.TestCase):
    def test_comments_only_yields_defaults(self):
        cfg = score.parse_yaml_subset("# 只有注释\n\n")
        self.assertEqual(cfg, {"strict": False, "weights": {}, "gates": []})

    def test_gate_inline_without_value(self):
        cfg = score.parse_yaml_subset("gates:\n  - path: \"a/*\"\n")
        self.assertEqual(cfg["gates"][0], {"path": "a/*"})

    def test_boolean_and_float_scalars(self):
        cfg = score.parse_yaml_subset("strict: false\nweight_x: 1.05\n")
        self.assertIs(cfg["strict"], False)
        self.assertEqual(cfg["weight_x"], 1.05)


class ConfigRobustTests(unittest.TestCase):
    def test_gates_string_falls_back_to_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".star-review.yaml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("gates: []\n")
            cfg, found = score.load_config(path)
            self.assertEqual(cfg["gates"], [])
            self.assertEqual(found, path)

    def test_weights_total_above_limit_rejected(self):
        with self.assertRaises(ValueError):
            score.effective_weights({"need": 0.4, "correct": 0.3, "security": 0.2,
                                     "maint": 0.2, "verify": 0.1})

    def test_weights_negative_rejected(self):
        with self.assertRaises(ValueError):
            score.effective_weights({"need": -0.1, "correct": 0.3, "security": 0.3,
                                     "maint": 0.3, "verify": 0.2})


# ---------------------------------------------------------------- v1.0 --init

class InitTests(unittest.TestCase):
    def test_init_creates_template(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                buf = StringIO()
                with redirect_stdout(buf):
                    code = score.main(["--init"])
                self.assertEqual(code, 0)
                self.assertTrue(os.path.isfile(".star-review.yaml"))
                self.assertIn("已生成", buf.getvalue())
            finally:
                os.chdir(cwd)

    def test_init_refuses_overwrite(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with open(".star-review.yaml", "w", encoding="utf-8") as fh:
                    fh.write("strict: true\n")
                buf = StringIO()
                with redirect_stdout(buf):
                    code = score.main(["--init"])
                self.assertEqual(code, 1)
                self.assertIn("已存在", buf.getvalue())
                with open(".star-review.yaml", encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "strict: true\n")  # 未被覆盖
            finally:
                os.chdir(cwd)

    def test_init_template_parseable_and_scoring(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with redirect_stdout(StringIO()):
                    score.main(["--init"])
                cfg, found = score.load_config()  # 自动查找
                self.assertIsNotNone(found)
                self.assertFalse(cfg["strict"])
                self.assertEqual(cfg["gates"], [])
                # 生成的模板权重可直接参与评分
                w = score.effective_weights(cfg["weights"])
                self.assertAlmostEqual(sum(w.values()), 1.0, places=4)
            finally:
                os.chdir(cwd)

    def test_init_template_mentions_version(self):
        self.assertIn(score.VERSION, score.YAML_TEMPLATE.format(version=score.VERSION))


# ---------------------------------------------------------------- v1.0 --format / --out

SCORE_ARGS = ["--need", "4", "--correct", "3", "--security", "4",
              "--maint", "3", "--verify", "2"]


class FormatOutTests(unittest.TestCase):
    def test_format_md_contains_table(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(SCORE_ARGS + ["--format", "md"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("### 代码评级", out)
        self.assertIn("| 维度 | 得分 | 权重 |", out)
        self.assertIn("| 需求达成 | 4/5 | 35% |", out)
        self.assertIn("**3.40**", out)

    def test_format_md_qa_title(self):
        buf = StringIO()
        with redirect_stdout(buf):
            score.main(["--mode", "qa", "--need", "4", "--correct", "5",
                        "--security", "4", "--maint", "4", "--verify", "3",
                        "--format", "md", "--turn", "2"])
        self.assertIn("问答评级 · 第 2 轮", buf.getvalue())

    def test_format_md_shows_caps(self):
        buf = StringIO()
        with redirect_stdout(buf):
            score.main(["--need", "5", "--correct", "5", "--security", "1",
                        "--maint", "5", "--verify", "5", "--format", "md"])
        self.assertIn("封顶", buf.getvalue())

    def test_format_json_valid(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(SCORE_ARGS + ["--format", "json"])
        self.assertEqual(code, 0)
        row = json.loads(buf.getvalue())
        self.assertEqual(row["stars"], 3)

    def test_json_flag_back_compat(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(SCORE_ARGS + ["--json"])
        self.assertEqual(code, 0)
        row = json.loads(buf.getvalue())
        self.assertEqual(row["weighted"], 3.40)

    def test_out_writes_file(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                buf = StringIO()
                with redirect_stdout(buf):
                    code = score.main(SCORE_ARGS + ["--format", "md", "--out", "card.md"])
                self.assertEqual(code, 0)
                self.assertIn("已写入 card.md", buf.getvalue())
                with open("card.md", encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn("### 代码评级", content)
                self.assertIn("| 维度 | 得分 | 权重 |", content)
            finally:
                os.chdir(cwd)

    def test_out_with_summary_appended(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                log = write_jsonl("log.jsonl", [sample_row(3)])
                buf = StringIO()
                with redirect_stdout(buf):
                    code = score.main(SCORE_ARGS + ["--format", "md", "--out", "card.md",
                                                    "--summary", log])
                self.assertEqual(code, 0)
                with open("card.md", encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn("### 代码评级", content)
                self.assertIn("共 1 轮", content)  # 汇总一并写入
            finally:
                os.chdir(cwd)

    def test_min_stars_fail_with_out_still_exits_1(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                err = StringIO()
                with redirect_stdout(StringIO()), redirect_stderr(err):
                    code = score.main(SCORE_ARGS + ["--out", "card.md", "--min-stars", "4"])
                self.assertEqual(code, 1)
                self.assertTrue(os.path.isfile("card.md"))  # 卡片仍已生成
                self.assertIn("门禁失败", err.getvalue())
            finally:
                os.chdir(cwd)

    def test_render_markdown_includes_verification(self):
        result = score.build(full_scores(), None, None, None, "",
                             extras={"verification": {"cmd": "pytest -q", "exit_code": 0,
                                                      "duration_s": 1.2, "tail": "1 passed"}})
        md = score.render_markdown(result)
        self.assertIn("pytest -q", md)
        self.assertIn("退出码 0", md)

    def test_render_markdown_includes_diff(self):
        result = score.build(full_scores(), None, None, None, "",
                             extras={"diff": {"files": [
                                 {"file": "a.py", "ins": 3, "del": 1}]}})
        md = score.render_markdown(result)
        self.assertIn("1 个文件，+3/-1", md)

    def test_render_markdown_includes_fix_items(self):
        result = score.build(full_scores(), None, None, None, "",
                             extras={"fix_items": ["补校验", "补测试"]})
        self.assertIn("补校验；补测试", score.render_markdown(result))

    def test_text_format_default_unchanged(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = score.main(SCORE_ARGS)
        self.assertEqual(code, 0)
        self.assertIn("最终评级", buf.getvalue())
        self.assertIn("加权分：3.40", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
