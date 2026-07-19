# 资源上传改造：assets/ 下的 PDF 按日期命名发到「综合资源」 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让资源上传脚本在「传入 assets/ 下的 .pdf」时，自动按 `2026-07-17_原名` 生成显示名/标题/简介，并归到工作室分类「综合资源」后提交；其余 PPTX 逻辑保持不变。

**Architecture:** 在 `resource_config.py` 新增纯函数 `resolve_pdf_asset()` 收口「PDF 来自 assets/」的字段构造（parentId=综合资源 + 日期命名）；两个上传脚本（`publish_resource_api.py` / `publish_resource_playwright.py`）的 `main()` 增加 pdf 模式自动识别，复用该函数，并把去重变体文件名改为日期前缀、写入临时目录避免污染 assets/。

**Tech Stack:** Python 3.13（managed venv），requests（api 版），playwright（playwright 版），既有的 `resource_config` 字段映射与 OSS 直传链路。

> 注：本仓库当前**不是 git 仓库**（`git rev-parse` 返回 128）。各 Task 末尾的 `git commit` 步骤可按需跳过；若要留存历史，先 `git init` 再提交。

---

## File Structure

- **Modify:** `resource_config.py` — 新增 `resolve_pdf_asset()`（在 `resolve_resource()` 之后）。
- **Create:** `tests/test_resource_config.py` — 纯函数单测（不依赖网络，可直接 `python` 运行）。
- **Modify:** `publish_resource_api.py` — `main()` 增加 pdf 模式识别 + 变体命名改临时目录。
- **Modify:** `publish_resource_playwright.py` — `main()` 同样增加 pdf 模式识别；step6 用 `move(综合资源value)` 设分类。
- **Modify:** `resources_config.json` — 在 `_说明` 补充一段 PDF 模式说明（不改 `fixed.parentId`，保留 PPTX 兜底）。

设计依据：`docs/superpowers/specs/2026-07-17-resource-pdf-upload-design.md`

---

### Task 1: 新增 `resolve_pdf_asset()` 并补单测（TDD）

**Files:**
- Create: `tests/test_resource_config.py`
- Modify: `resource_config.py`（在 `resolve_resource()` 函数之后追加）

- [ ] **Step 1: 写失败测试**

`tests/test_resource_config.py`:
```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from resource_config import resolve_pdf_asset, PARENTID_OPTIONS


def test_pdf_asset_default_naming():
    fields, src = resolve_pdf_asset("/any/assets/fur_elise.pdf", "2026-07-17")
    assert fields["title"] == "2026-07-17_fur_elise"
    assert fields["intro"] == "2026-07-17_fur_elise"
    assert fields["file"] == "/any/assets/fur_elise.pdf"
    assert fields["parentId"] == PARENTID_OPTIONS["综合资源"]
    assert fields["rtype"] == PARENTID_OPTIONS["综合资源"]
    assert src == "pdf-asset 2026-07-17_fur_elise"


def test_pdf_asset_title_override():
    fields, src = resolve_pdf_asset("/any/assets/fur_elise.pdf", "2026-07-17", title="自定义名")
    assert fields["title"] == "自定义名"
    assert fields["intro"] == "自定义名"


def test_pdf_asset_title_and_intro_override():
    fields, src = resolve_pdf_asset("/any/assets/fur_elise.pdf", "2026-07-17",
                                    title="T", intro="I")
    assert fields["title"] == "T"
    assert fields["intro"] == "I"


if __name__ == "__main__":
    test_pdf_asset_default_naming()
    test_pdf_asset_title_override()
    test_pdf_asset_title_and_intro_override()
    print("ALL TESTS PASSED")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python tests/test_resource_config.py`
Expected: `AttributeError: module 'resource_config' has no attribute 'resolve_pdf_asset'`

- [ ] **Step 3: 实现 `resolve_pdf_asset()`**

在 `resource_config.py` 的 `resolve_resource()` 函数（约 242 行 `raise SystemExit(...)` 之后）追加：
```python
def resolve_pdf_asset(pdf_path, date, title=None, intro=None):
    """assets/ 下的 PDF 专用：parentId=综合资源，title/intro=YYYY-MM-DD_原名。

    供 publish_resource_api.py / publish_resource_playwright.py 在「传入 assets/ 下 .pdf」
    时调用，替代 resolve_resource()。date 默认 today_str()（也可由 --date 覆盖）。
    """
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    name = f"{date}_{stem}"            # 2026-07-17_fur_elise
    fields = dict(DEFAULT_FIXED)
    fields["parentId"] = "综合资源"    # normalize 翻成真实 value 并同步 rtype
    fields["file"] = pdf_path
    fields["title"] = title or name
    fields["intro"] = intro or (title or name)
    return normalize_fields(fields), f"pdf-asset {name}"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python tests/test_resource_config.py`
Expected: `ALL TESTS PASSED`

- [ ] **Step 5: 提交（可选）**

```bash
git add resource_config.py tests/test_resource_config.py
git commit -m "feat: add resolve_pdf_asset for assets/ PDF uploads (综合资源 + date naming)"
```

---

### Task 2: `publish_resource_api.py` 接入 pdf 模式

**Files:**
- Modify: `publish_resource_api.py`（import 行、main() 解析字段段、源文件兜底段、变体命名段）

- [ ] **Step 1: 更新 import**

将第 32 行：
```python
from resource_config import resolve_resource, list_resources, _default_config_path
```
改为：
```python
from resource_config import (resolve_resource, list_resources,
                             _default_config_path, resolve_pdf_asset, today_str)
```
并在文件顶部 import 区（`import sys, os, re, hashlib, time, argparse` 一行）追加 `tempfile`：
```python
import sys, os, re, hashlib, time, argparse, tempfile
```

- [ ] **Step 2: 在 main() 解析字段处接入 pdf 模式**

将 main() 中 `args = ap.parse_args()` 之后、`if args.list:` 块之后的字段解析段（原第 182-189 行附近）：
```python
    fields, source = resolve_resource(
        config_path=args.config, override_date=args.date,
        cli_file=args.file, cli_title=args.title, cli_intro=args.intro)
    log(f"来源: {source}")
    src = fields.get("file")
    if not src:
        raise SystemExit("配置缺少 file 字段(源 pptx 路径)")
```
替换为：
```python
    # ---- PDF 模式自动识别: assets/ 下的 .pdf ----
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    _p = os.path.abspath(args.file) if args.file else ""
    pdf_mode = bool(args.file) and args.file.lower().endswith(".pdf") and \
               os.path.dirname(_p) == assets_dir

    if pdf_mode:
        date = args.date or today_str()
        fields, source = resolve_pdf_asset(args.file, date, args.title, args.intro)
    else:
        fields, source = resolve_resource(
            config_path=args.config, override_date=args.date,
            cli_file=args.file, cli_title=args.title, cli_intro=args.intro)
    log(f"来源: {source}  pdf_mode={pdf_mode}")
    src = fields.get("file")
    if not src:
        raise SystemExit("配置缺少 file 字段(源 pptx 路径)")
```

- [ ] **Step 3: 源文件兜底按 pdf 模式区分**

将原第 193-199 行的源文件兜底段：
```python
    # 源文件兜底
    if not os.path.exists(src):
        alt = os.path.join(os.getcwd(), "《铃儿响叮当》 课件 上传3.pptx")
        if os.path.exists(alt):
            src = alt
            log(f"源文件不存在, 改用: {alt}")
        else:
            raise SystemExit("找不到源 pptx 文件, 请检查配置 file 路径")
```
替换为：
```python
    # 源文件兜底（仅非 PDF 模式沿用旧的 pptx 兜底）
    if not os.path.exists(src):
        if pdf_mode:
            raise SystemExit(f"找不到 PDF 文件: {src}")
        alt = os.path.join(os.getcwd(), "《铃儿响叮当》 课件 上传3.pptx")
        if os.path.exists(alt):
            src = alt
            log(f"源文件不存在, 改用: {alt}")
        else:
            raise SystemExit("找不到源 pptx 文件, 请检查配置 file 路径")
```

- [ ] **Step 4: 变体命名改为日期前缀 + 临时目录**

将原第 206-211 行：
```python
    workdir = os.path.dirname(os.path.abspath(src)) or "."
    ts = time.strftime("%Y%m%d_%H%M%S")
    stem, ext = os.path.splitext(os.path.basename(src))
    variant = os.path.join(workdir, f"{stem} api_{ts}{ext}")
    make_variant(src, variant)
    log(f"生成去重变体(新MD5): {variant}")
```
替换为：
```python
    stem, ext = os.path.splitext(os.path.basename(src))
    if pdf_mode:
        date = args.date or today_str()
        # 日期前缀命名，写到临时目录避免污染 assets/
        variant = os.path.join(tempfile.gettempdir(), f"{date}_{stem}{ext}")
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        workdir = os.path.dirname(os.path.abspath(src)) or "."
        variant = os.path.join(workdir, f"{stem} api_{ts}{ext}")
    make_variant(src, variant)
    log(f"生成去重变体(新MD5): {variant}")
```
（后续 `title = fields.get("title") or ...` / `fields["title"] = title` / `intro` 兜底逻辑保持不变——pdf 模式下 `resolve_pdf_asset` 已写好 title/intro，会原样保留。）

- [ ] **Step 5: 语法自检**

Run: `cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "import publish_resource_api; print('ok')"`
Expected: `ok`

- [ ] **Step 6: 提交（可选）**

```bash
git add publish_resource_api.py
git commit -m "feat: publish_resource_api detects assets/ .pdf -> 综合资源 + date naming"
```

---

### Task 3: `publish_resource_playwright.py` 接入 pdf 模式

**Files:**
- Modify: `publish_resource_playwright.py`（import 行、main() 解析段、变体命名段、step6 工作室分类段）

- [ ] **Step 1: 更新 import**

将第 32 行：
```python
from resource_config import resolve_resource, list_resources, _default_config_path
```
改为：
```python
from resource_config import (resolve_resource, list_resources,
                             _default_config_path, resolve_pdf_asset, today_str)
```

- [ ] **Step 2: main() 解析字段处接入 pdf 模式**

将第 88-99 行：
```python
    # 命令行 pptx 作为 file 覆盖; 仅给 pptx 未给 title 时, title 取文件名
    cli_file = args.pptx
    cli_title = args.title
    if cli_file and not cli_title:
        cli_title = os.path.splitext(os.path.basename(cli_file))[0]
    fields, source = resolve_resource(
        config_path=args.config, override_date=args.date,
        cli_file=cli_file, cli_title=cli_title)
    log(f"来源: {source}")
    src = fields.get("file")
    if not src:
        raise SystemExit("配置缺少 file 字段(源 pptx 路径)")
```
替换为：
```python
    # ---- PDF 模式自动识别: assets/ 下的 .pdf ----
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    _p = os.path.abspath(args.pptx) if args.pptx else ""
    pdf_mode = bool(args.pptx) and args.pptx.lower().endswith(".pdf") and \
               os.path.dirname(_p) == assets_dir

    if pdf_mode:
        date = args.date or today_str()
        fields, source = resolve_pdf_asset(args.pptx, date, args.title)
        cli_file = args.pptx
    else:
        cli_file = args.pptx
        cli_title = args.title
        if cli_file and not cli_title:
            cli_title = os.path.splitext(os.path.basename(cli_file))[0]
        fields, source = resolve_resource(
            config_path=args.config, override_date=args.date,
            cli_file=cli_file, cli_title=cli_title)
    log(f"来源: {source}  pdf_mode={pdf_mode}")
    src = fields.get("file")
    if not src:
        raise SystemExit("配置缺少 file 字段(源 pptx 路径)")
```

- [ ] **Step 3: 变体命名改为日期前缀 + 临时目录**

将第 110-119 行：
```python
    if args.no_variant:
        pptx = src
        log("使用原文件 (未改 MD5, 可能触发服务端去重)")
    else:
        workdir = os.path.dirname(os.path.abspath(src)) or "."
        ts = time.strftime("%Y%m%d_%H%M%S")
        stem, ext = os.path.splitext(os.path.basename(src))
        pptx = os.path.join(workdir, f"{stem} pw_{ts}{ext}")
        make_variant(src, pptx)
        log("生成去重变体:", pptx)
```
替换为：
```python
    if args.no_variant:
        pptx = src
        log("使用原文件 (未改 MD5, 可能触发服务端去重)")
    else:
        stem, ext = os.path.splitext(os.path.basename(src))
        if pdf_mode:
            date = args.date or today_str()
            pptx = os.path.join(tempfile.gettempdir(), f"{date}_{stem}{ext}")
        else:
            workdir = os.path.dirname(os.path.abspath(src)) or "."
            ts = time.strftime("%Y%m%d_%H%M%S")
            pptx = os.path.join(workdir, f"{stem} pw_{ts}{ext}")
        make_variant(src, pptx)
        log("生成去重变体:", pptx)
```
（注意：本文件顶部 import 需补 `import tempfile`，加入 `import os, re, time, argparse, tempfile`。）

- [ ] **Step 4: step6 工作室分类按 pdf 模式用 move()**

将第 229-238 行：
```python
        # ---- 6) 工作室分类 PPT (点 <a> 触发 move) ----
        log("--- step6: 工作室分类=PPT ---")
        try:
            page.click("#treeDemo2_10_a", force=True, timeout=5000)
        except Exception as e:
            log(f"click #treeDemo2_10_a 失败: {e}; 调 move()")
            page.evaluate("""() => { try{ if(typeof move==='function') move('db1a78ebac1d2c2f2970bbf81f0d1a61'); }catch(e){} }""")
        page.wait_for_timeout(1200)
        pid = page.evaluate("()=>document.querySelector('#parentId')?.value||'(not found)'")
        log(f"parentId={pid!r}")
```
替换为：
```python
        # ---- 6) 工作室分类 ----
        if pdf_mode:
            log("--- step6: 工作室分类=综合资源 (move) ---")
            page.evaluate(
                "() => { try{ if(typeof move==='function') move('%s'); }catch(e){} }"
                % fields["parentId"])
        else:
            log("--- step6: 工作室分类=PPT ---")
            try:
                page.click("#treeDemo2_10_a", force=True, timeout=5000)
            except Exception as e:
                log(f"click #treeDemo2_10_a 失败: {e}; 调 move()")
                page.evaluate("""() => { try{ if(typeof move==='function') move('db1a78ebac1d2c2f2970bbf81f0d1a61'); }catch(e){} }""")
        page.wait_for_timeout(1200)
        pid = page.evaluate("()=>document.querySelector('#parentId')?.value||'(not found)'")
        log(f"parentId={pid!r}")
```

- [ ] **Step 5: 语法自检**

Run: `cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "import publish_resource_playwright; print('ok')"`
Expected: `ok`

- [ ] **Step 6: 提交（可选）**

```bash
git add publish_resource_playwright.py
git commit -m "feat: publish_resource_playwright detects assets/ .pdf -> 综合资源 + date naming"
```

---

### Task 4: `resources_config.json` 补充 PDF 模式说明

**Files:**
- Modify: `resources_config.json`（仅 `_说明` 字段，新增一句；不改 `fixed`）

- [ ] **Step 1: 在 `_说明` 开头补充 PDF 模式说明**

将 `_说明` 现有文本开头追加一段（用中文逗号衔接即可，保持整段 JSON 合法字符串）：
```
"PDF 模式：若命令行传入位于 assets/ 目录下、以 .pdf 结尾的文件，脚本自动进入 PDF 模式——"
"资源标题/简介按「YYYY-MM-DD_原文件名」生成，工作室分类强制为「综合资源」，其余固定字段沿用默认；"
"其它（如传入 pptx 或不传文件走配置）仍按原逻辑。批量发布示例："
"for f in assets/*.pdf; do python publish_resource_api.py cookies.txt \"$f\"; done"
```

- [ ] **Step 2: 校验 JSON 合法**

Run: `cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "import json; json.load(open('resources_config.json',encoding='utf-8')); print('json ok')"`
Expected: `json ok`

- [ ] **Step 3: 提交（可选）**

```bash
git add resources_config.json
git commit -m "docs: note PDF mode in resources_config"
```

---

### Task 5: 集成验证（api 版 dry-run + 正式发一条）

**Files:**
- 仅需已存在的 `assets/fur_elise.pdf`（或任意 assets/ 下的 PDF）与有效 `cookies.txt`

- [ ] **Step 1: dry-run 预览字段与 OSS 显示名**

Run:
```bash
cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python publish_resource_api.py cookies.txt assets/fur_elise.pdf --dry-run
```
Expected（关键行）:
```
来源: pdf-asset 2026-07-17_fur_elise  pdf_mode=True
[1/4] ossGetAuthorization  fileName=2026-07-17_fur_elise.pdf ...
[4/4] 提交资源表单 ...   (dry-run 仅预览)
    title = 2026-07-17_fur_elise
    intro = 2026-07-17_fur_elise
    parentId = a14c5ca55abf3be32f4f83e543311b74
    rtype = a14c5ca55abf3be32f4f83e543311b74
```
（日期取当天；若用 `--date 2026-07-14` 则前缀为 2026-07-14。）

- [ ] **Step 2: 正式发一条验证**

Run:
```bash
cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python publish_resource_api.py cookies.txt assets/fur_elise.pdf
```
Expected: 末尾 `✅ 提交成功 (type=1)`。随后到工作室「综合资源」分类下核对：显示名 `2026-07-17_fur_elise`、文件可下载。

- [ ] **Step 3: 批量冒烟（前 2~3 条）**

Run:
```bash
cd /Users/matthew/workshop/clock && i=0; for f in assets/*.pdf; do
  /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python publish_resource_api.py cookies.txt "$f" && i=$((i+1));
  [ $i -ge 3 ] && break; done
```
Expected: 每条均 `type=1`，命名/分类正确，无去重拦截（type=2）。

---

## Self-Review（与 spec 对照）

1. **Spec 覆盖**：
   - 单 PDF 命令行指定 → Task 2/3 pdf 模式识别（`assets/` 下 `.pdf`）。
   - `2026-07-17_原名` 格式（file/title/intro）→ Task 1 `resolve_pdf_asset` + Task 2/3 变体命名。
   - parentId=综合资源 → Task 1（normalize 翻值+同步 rtype）、Task 2/3 字段使用、Task 3 step6 `move()`。
   - 自动识别、不新增参数、保留 PPTX 兜底 → Task 2/3 分支 + Task 4（不改 fixed.parentId）。
   - 变体写临时目录避免污染 assets/ → Task 2/3。
   全部有对应 Task。
2. **占位符扫描**：无 TBD/TODO；每个代码 Step 均有完整片段。
3. **类型一致性**：`resolve_pdf_asset(pdf_path, date, title, intro)` 签名在 Task 1 定义、Task 2/3 调用一致；`fields["parentId"]` 在 Task 3 step6 作为 `move()` 参数，与 Task 1 normalize 后的值一致。
4. **未覆盖项**：playwright 版 step6 用 `move('<value>')` 而非点树节点（树节点序号未知），已在设计中说明为 JS 兜底同款做法；实网验证需有效 cookie + 浏览器，列入 Task 5 手动验证。
