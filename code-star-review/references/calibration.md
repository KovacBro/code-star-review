# 校准案例

用于对齐"什么算几星"。每个案例都给出**为什么不是更高或更低**，这是打分一致性的关键。

---

## 案例 A — 5 星（可直接合并）

**场景**：新增 `parse_duration("1h30m") -> 5400` 工具函数。

```python
import re

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_PATTERN = re.compile(r"(\d+)\s*([smhd])")

def parse_duration(text: str) -> int:
    """把 '1h30m' 解析为秒数，非法输入抛 ValueError。"""
    if not text or not text.strip():
        raise ValueError("duration cannot be empty")
    total, matched = 0, 0
    for value, unit in _PATTERN.findall(text.lower()):
        total += int(value) * _UNITS[unit]
        matched += len(value) + len(unit)
    if matched == 0 or not _PATTERN.fullmatch(text.lower().replace(" ", "")):
        raise ValueError(f"invalid duration: {text!r}")
    return total
```

**评分**：需求 5 / 正确 5 / 安全 5 / 可维护 5 / 验证 5 → **5.0 → ★★★★★**

**证据**
- 空串、纯空白、非法字符、大小写、空格全部处理（函数内 3 处判断）。
- 错误信息含原值 `{text!r}`，便于排查。
- 常量表 + 正则，无重复分支；函数 12 行。
- 附 4 条 pytest（`test_parse_duration.py`），含 `-1h`、`1x` 异常用例，运行输出 4 passed。

**为什么不是 4 星**：异常路径有测试、失败可预期、无遗留瑕疵，找不到 P3 以上问题。
**什么情况会掉到 4 星**：没有测试，仅口头说"我试过"。

---

## 案例 B — 4 星（可直接使用，有非阻断瑕疵）

**场景**：给现有 `UserService` 增加按邮箱查用户。

```python
def get_by_email(self, email):
    user = self.repo.find_one({"email": email})
    if not user:
        raise NotFound("user not found")
    return user
```

**评分**：需求 5 / 正确 4 / 安全 4 / 可维护 3 / 验证 3 → **4.10 → ★★★★☆**

**证据**
- 需求达成，未命中任何 Gate。
- 未做 `email.strip().lower()` 归一化，大小写不同的邮箱查不到（`user_service.py:41`）——P2。
- 未校验 email 格式，但由上游注册接口保证，风险低。
- 方法名与项目其他查询一致；缺点是缺类型注解，与同文件其他方法风格不符。
- 有手动 curl 验证记录，无单测。

**为什么不是 3 星**：主流程正确，缺陷只影响边缘输入，不产生脏数据，属于 P2 但可通过一处小修解决。
**为什么不是 5 星**：归一化缺失 + 无测试，两条都够不上"可直接合并"。

---

## 案例 C — 3 星（可用有债，最常见的分数）

**场景**：实现分页查询接口。

```python
@app.get("/orders")
def list_orders():
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 20))
    rows = Order.query.order_by(Order.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"items": [r.to_dict() for r in rows]}
```

**评分**：需求 4 / 正确 3 / 安全 3 / 可维护 3 / 验证 2 → **3.25 → ★★★☆☆**

**证据**
- 分页逻辑正确，happy path 可用。
- `page=0` 或 `page=abc` 会抛 500（未校验入参，`order_api.py:22`）——P2。
- 无 `size` 上限，`size=999999` 可拖垮数据库——P2/安全低危。
- 未返回总数，前端无法渲染页码——P2。
- 无测试、无运行记录。

**为什么不是 4 星**：入参会打崩接口、缺 total 字段，属于功能与健壮性的实质缺口。
**为什么不是 2 星**：主流程正确，错误只发生在非法输入，不产生脏数据，小修即可解决。

> 对照案例 D：同样是"能跑"，但 D 在失败时会写坏数据并放大，所以掉到 2 星。**关键差别是失败后果，不是失败概率。**

---

## 案例 C2 — 看起来像 3 星，实际 1 星

**场景**：文件上传接口。

```python
@app.post("/upload")
def upload():
    f = request.files["file"]
    f.save(f"/data/uploads/{f.filename}")
    return {"url": f"/files/{f.filename}"}
```

**评分**：**★☆☆☆☆ 1/5**（G1：路径穿越 + 无任何校验）

**证据**
- `f.filename` 直接拼路径，传 `../../etc/passwd` 可写出目录外文件（高危）。
- 无类型白名单、无大小限制、同名覆盖。
- 即使功能"能跑通一次"，也不能投入任何可被外部访问的环境。

**常见误判**：因为它只有 5 行、请求成功返回 200，容易被评成 3 星"能用但有债"。**安全维度 ≤1 时不要用其他维度拉分**，Gate 会直接封顶。

---

## 案例 D — 2 星（半成品，失败留脏数据）

**场景**：批量导入 CSV 到订单表。

```python
def import_orders(path):
    rows = list(csv.DictReader(open(path)))
    for row in rows:
        order = Order(no=row["no"], amount=float(row["amount"]))
        db.session.add(order)
        db.session.commit()          # 每行提交
    return {"count": len(rows)}
```

**评分**：需求 4 / 正确 3 / 安全 4 / 可维护 3 / 验证 1 → 加权 3.30（原始 3★），但命中 **G2**（失败路径留脏数据）→ 封顶 **2 星**

**证据**
- 无表头校验、无金额校验；`float("abc")` 在第 500 行抛错时，前 499 行已入库，且接口返回 500，调用方会重试 → 重复订单（P1）。
- 每行 commit，性能差。
- 无幂等键、无事务边界。
- 无测试。

**为什么不是 3 星**：失败会产生脏数据并因重试放大，属于数据正确性问题，不是"可小修的债"。
**为什么不是 1 星**：happy path 完全正确，需求也基本达成，不属于方向错误。

---

## 案例 E — 1 星（不可用，方向/实现错误）

**场景**：要求"删除订单"，实现为：

```python
def delete_order(order_id):
    db.session.query(Order).filter(Order.id == order_id).update({"deleted": 1})
    db.session.commit()
```

但 `Order` 模型没有 `deleted` 字段，且所有查询都没过滤 `deleted`。

**评分**：**★☆☆☆☆ 1/5**（G1：核心需求未实现 + 主流程报错）

**证据**
- `update({"deleted": 1})` 会抛 `InvalidRequestError`（模型无此列），接口必崩。
- 即使补上字段，查询侧未过滤，等于没删——需求未达成。
- 单测缺失。

**为什么不是 0 星**：有明确意图和可修补的代码骨架，不是空产出或恶意代码。
**为什么不是 2 星**：不是"缺一块"，而是主流程直接失败 + 需求语义没实现。

---

## 案例 F — 0 星（无效/有害）

**场景 A**：回答"已修复并测试通过 ✅"，但 diff 为空，测试文件是 `def test_x(): pass`。
**场景 B**：为"方便调试"，把 `AKIA...` 生产密钥写进 `config.py` 并提交。
**场景 C**：声称"清理缓存"，实际执行 `shutil.rmtree("/")`。

三者均为 **☆☆☆☆☆ 0/5**：
- A 命中 G0「伪造验证结果」——比不验证更严重，直接 0。
- B 命中 G0「硬编码密钥」+ G1，取 0。
- C 命中 G0「破坏性改动」。

**判定要点**：0 星不是"代码写得差"，而是**没有有效产出或产出有害**。代码差但有骨架，最低也是 1 星。

---

## 案例 G — 4 星（TS/React 组件）

**场景**：新增 React 组件 `<FileSizeInput>`，限制上传大小并回显人类可读尺寸。

```tsx
export function FileSizeInput({ maxSizeMB, onChange }: Props) {
  const [err, setErr] = useState<string | null>(null);
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > maxSizeMB * 1024 * 1024) {
      setErr(`最大 ${maxSizeMB}MB`);
      return;
    }
    setErr(null);
    onChange(file);
  };
  return (
    <label>
      <input type="file" onChange={handleChange} />
      {err && <span role="alert">{err}</span>}
    </label>
  );
}
```

**评分**：需求 5 / 正确 4 / 安全 5 / 可维护 4 / 验证 2 → **4.00 → ★★★★☆**

**证据**
- 大小校验、错误回显（`role="alert"`）符合需求；未选中文件时静默返回属合理行为。
- `maxSizeMB` 为 0 或负数时不做防御（`FileSizeInput.tsx:5`）——P3，由调用方约束。
- 无 `accept` 属性限制文件类型——P3，需求未要求。
- 无测试（缺 `@testing-library/react` 用例），无渲染验证记录——验证 2。

**为什么不是 3 星**：主流程正确，缺陷全是 P3 级，不产生脏数据或安全问题。
**为什么不是 5 星**：无测试无运行证据，且 5 星要求"可直接合并"——前端组件至少要一次真实渲染验证。

---

## 案例 H — 2 星（SQL 迁移脚本，Gate 封顶）

**场景**：需求是"给 orders 表加 `status` 列，默认 `'pending'`"。

```sql
-- migrations/003_add_status.sql
ALTER TABLE orders DROP COLUMN legacy_flag;
ALTER TABLE orders ADD COLUMN status VARCHAR(20);
UPDATE orders SET status = 'paid';
```

**评分**：需求 1 / 正确 1 / 安全 1 / 可维护 2 / 验证 2 → 加权 1.30，同时命中 **G1（核心需求未实现+破坏性改动）** → 封顶 **2 星**（多文件规则下按最差文件定 Gate；此处维度分与 Gate 一致取低）

**证据**
- 需求要加列，脚本却先 `DROP COLUMN legacy_flag`——超出需求且**不可逆**（migration/003:2）。
- `status` 列无 `NOT NULL DEFAULT 'pending'`，新旧行语义不一致（migration/003:3）。
- `UPDATE ... SET status='paid'` 把**全表**改成 paid——与默认值需求相反，直接资损级错误（migration/003:4）。
- 无备份/回滚语句，无行数预估。

**常见误判**："迁移脚本是配置，能执行就行"——错。迁移脚本的标准卡必须用**严格卡**（`output-formats.md` §3），任何不可逆操作无备份/回滚即封顶。
**为什么不是 1 星**：语法正确、可执行，骨架还在，属于"方向部分错误+破坏性"而非完全无效。

---

## 案例 I — 3 星（Dockerfile）

**场景**："把 FastAPI 服务容器化，生产可用。"

```dockerfile
FROM python:3.12
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]
```

**评分**：需求 3 / 正确 4 / 安全 2 / 可维护 3 / 验证 3 → **3.10 → ★★★☆☆**

**证据**
- 能构建能跑，`COPY . .` 未用 `.dockerignore`，把 `.git`、本地缓存全部打进镜像（Dockerfile:3）。
- 以 root 运行，无 `USER` 指令——中危（Dockerfile:1）。
- 无多阶段构建，镜像体积大；依赖变更会击穿全部缓存层（Dockerfile:4，应先 COPY requirements.txt 再 install）。
- 未固定基础镜像 digest/tag（`python:3.12` 浮动标签）——可复现性缺口。
- 声称"本地构建通过"，无 `docker run` 冒烟输出。

**为什么不是 4 星**：root 运行 + COPY 泄漏是实质安全/工程缺口，修完才有资格谈 4 星。
**为什么不是 2 星**：功能目标达成，服务可运行，失败不会损坏数据——属"可用有债"。

---

## 快速对照

| 如果看到 | 大概星级 |
| --- | --- |
| 空 diff、只有解释、伪造测试 | 0 |
| 跑不起来、需求做反、核心函数是 `pass` | 1 |
| 能跑 demo、失败留脏数据、关键功能缺块 | 2 |
| happy path 对、无校验/无异常/无测试 | 3 |
| 功能完整、少量命名或边界瑕疵 | 4 |
| 全验收点 + 异常边界 + 测试证据 + 改动最小 | 5 |

**非代码/其他形态速判**：
| 形态 | 大概星级信号 |
| --- | --- |
| React/TS 组件 | 逻辑正确+可访问性到位=4；+测试=5；无任何渲染验证 ≤3 |
| SQL 迁移 | 任何不可逆操作无备份/回滚 → 封顶 2；全表 UPDATE 语义错误 → G1 |
| Dockerfile/CI 配置 | root 运行/浮动标签/COPY 泄漏 → 3；能跑+最小化+非 root+固定版本 → 4 |
| 问答/分析回答（qa 模式） | 答非所问 → 封顶 1；结论无依据 → ≤3；有出处+覆盖例外+可复现 → 5 |
