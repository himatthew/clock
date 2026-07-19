# 资源上传改造：assets/ 下的 PDF 自动按日期命名发到「综合资源」

- 日期：2026-07-17
- 状态：已与用户确认设计，待实现

## 1. 目标

把「之江汇教育广场（陈晓雯名师工作室 sid=2174）」的资源上传逻辑，从当前写死的 PPTX
（`/Users/matthew/Downloads/《铃儿响叮当》课件.pptx` + `parentId=PPT`）改造为：

> 每次运行**命令行指定一个 `assets/` 下的 PDF**，自动按「**今天日期 + 原文件名**」生成
> 上传显示名 / 资源标题 / 简介，并归到工作室分类 **综合资源** 后提交。

为后续把 `assets/` 里已收集的 100 个钢琴谱 PDF 批量发布做准备。

## 2. 已确认的关键决策（来自澄清）

1. **上传范围**：每次运行通过命令行参数指定**单个** PDF，例如
   `python publish_resource_api.py cookies.txt assets/fur_elise.pdf`。一次一个，方便用 shell
   循环批量发完 100 个。
2. **命名格式**：`2026-07-17_原名`（下划线连接）。
   - OSS 上传显示名 = `2026-07-17_fur_elise.pdf`
   - 资源 `title` = `2026-07-17_fur_elise`（去扩展名）
   - 资源 `intro` = 与 `title` 相同（用户明确要求 file/title/intro 三者都按此生成）
3. **触发方式**：**自动识别**——传入的 `file` 若以 `.pdf` 结尾且绝对路径位于
   `<脚本目录>/assets/` 下，则进入 PDF 模式（日期命名 + parentId=综合资源）；传 PPTX 仍走
   原配置逻辑。不新增命令行开关，不改原有 PPTX 行为。
4. **parentId = 综合资源**（页面真实值 `a14c5ca55abf3be32f4f83e543311b74`，由
   `resource_config.PARENTID_OPTIONS` 映射，提交时 `rtype` 自动同步为该值）。

## 3. 当前实现现状（改造前）

- `publish_resource_api.py` / `publish_resource_playwright.py`：OSS 直传 + 表单提交。
  - `oss_upload()` 用 `os.path.basename(path)` 作为 OSS 显示名（`fname`）。
  - `main()` 生成去重变体：`{stem} api_{ts}{ext}`，写到**源文件同目录**（会污染 assets/），
    并追加随机字节改 MD5 绕过去重。
- `resource_config.py`：
  - `DEFAULT_FIXED` 与 `resources_config.json` 的 `fixed` 段都写 `parentId: "PPT"`。
  - `resolve_resource()` 优先级：CLI `--file/--title` > 配置按 `date==运行日` > `default`。
  - `normalize_fields()` 把可读中文名翻译成页面 value，并把 `parentId` 同步到 `rtype`。

## 4. 设计

### 4.1 `resource_config.py` 新增 `resolve_pdf_asset()`

收口「PDF 来自 assets/」的字段构造，供两个上传脚本共用：

```python
def resolve_pdf_asset(pdf_path, date, title=None, intro=None):
    """assets/ 下的 PDF 专用：parentId=综合资源，title/intro=YYYY-MM-DD_原名。"""
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    name = f"{date}_{stem}"            # 2026-07-17_fur_elise
    fields = dict(DEFAULT_FIXED)
    fields["parentId"] = "综合资源"    # normalize 翻成真实 value 并同步 rtype
    fields["file"]  = pdf_path
    fields["title"] = title or name
    fields["intro"] = intro or (title or name)
    return normalize_fields(fields), f"pdf-asset {name}"
```

- 其它固定字段保持 `DEFAULT_FIXED`（classid=课件 / subject=音乐 / period=小学 /
  edition=其它 / public_status=开放下载 / original=本人原创 / original_author=洪彦）——
  用户只要求改 parentId 与 file/title/intro。
- `date` 默认取 `today_str()`；支持 `--date` 覆盖（与现有 `override_date` 一致）。

### 4.2 `publish_resource_api.py` 的 `main()`

1. **判定 pdf 模式**：
   ```python
   assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
   p = os.path.abspath(args.file) if args.file else ""
   pdf_mode = bool(args.file) and args.file.lower().endswith(".pdf") and \
              os.path.dirname(p) == assets_dir
   ```
2. **解析字段**：
   ```python
   if pdf_mode:
       date = args.date or today_str()
       fields, source = resolve_pdf_asset(args.file, date, args.title, args.intro)
   else:
       fields, source = resolve_resource(config_path=args.config,
                                          override_date=args.date,
                                          cli_file=args.file,
                                          cli_title=args.title,
                                          cli_intro=args.intro)
   ```
   （`--title` / `--intro` 仍可作为覆盖；不传则自动用日期命名。）
3. **变体文件命名改为日期前缀 + 写到临时目录**（避免污染 assets/）：
   ```python
   stem, ext = os.path.splitext(os.path.basename(src))
   if pdf_mode:
       date = args.date or today_str()
       variant_name = f"{date}_{stem}{ext}"          # 2026-07-17_fur_elise.pdf
       workdir = tempfile.gettempdir()
   else:
       ts = time.strftime("%Y%m%d_%H%M%S")
       variant_name = f"{stem} api_{ts}{ext}"
       workdir = os.path.dirname(os.path.abspath(src)) or "."
   variant = os.path.join(workdir, variant_name)
   make_variant(src, variant)   # 仍追加随机字节改 MD5 绕过去重
   ```
   - OSS 显示名 = `os.path.basename(variant)` = `2026-07-17_fur_elise.pdf`。
   - 临时目录中的变体在上传后即失去用途；可由系统/用户后续清理（不在脚本内删除，保持简单）。

### 4.3 `publish_resource_playwright.py`

套用**同一套** pdf 模式判定与 `resolve_pdf_asset()`，确保两个上传入口行为一致。
（若用户只使用 api 版，可暂缓；本次默认一并改造。）

### 4.4 `resources_config.json`

- `fixed.parentId` **保持 `"PPT"`**（作为 PPTX 兜底），不全局改。
- 综合资源只在 pdf 模式由脚本覆盖，避免影响旧 PPTX 流程。
- 可选：在 `_说明` 中补充一段「PDF 模式：传入 assets/ 下 .pdf 即自动日期命名并归综合资源」。

## 5. 数据流（一次运行）

```
assets/fur_elise.pdf
  └─ 判定 pdf 模式 (assets/ 下 .pdf)
       ├─ 生成临时变体 /tmp/2026-07-17_fur_elise.pdf (追加随机字节→新 MD5)
       ├─ OSS 直传 → 显示名 2026-07-17_fur_elise.pdf, 返回 fid
       └─ 提交表单: title=2026-07-17_fur_elise,
                    intro=2026-07-17_fur_elise,
                    parentId=a14c5ca55abf3be32f4f83e543311b74,
                    rtype=a14c5ca55abf3be32f4f83e543311b74,
                    (其余固定字段沿用 DEFAULT_FIXED)
```

## 6. 边界与错误处理

- **非 assets/ 下的 .pdf**：不进入 pdf 模式，回退到原 `resolve_resource()`（按配置/CLI）。
- **pdf 模式但文件不存在**：沿用现有 `os.path.exists(src)` 兜底与 `SystemExit` 提示。
- **`--title` 显式传入**：优先于日期命名（覆盖 `title`，`intro` 默认跟随 `title`）。
- **重复运行同一 PDF**：变体追加随机字节改 MD5，配合跳过 rapidUpload 秒传，确保拿到新 fid，
  不被服务端去重拦截（type=2）。显示名相同不影响。
- **cookie 失效**：OSS 授权/提交会报错，沿用现有异常提示（需先 `refresh_cookie.py`）。

## 7. 测试

1. **命名与字段预览**（不需真发）：
   `python publish_resource_api.py cookies.txt assets/fur_elise.pdf --dry-run`
   - 确认预览 `title=2026-07-17_fur_elise`、`intro=2026-07-17_fur_elise`、
     `parentId=a14c5ca55abf3be32f4f83e543311b74`、`rtype=a14c5ca55abf3be32f4f83e543311b74`。
   - 确认 OSS `fname` = `2026-07-17_fur_elise.pdf`（看 `[1/4] ossGetAuthorization fileName=` 日志）。
2. **正式发一条**：去掉 `--dry-run`，确认返回 `type=1`（提交成功）；到工作室「综合资源」分类下
   核对显示名为 `2026-07-17_fur_elise`、文件可下载。
3. **批量冒烟**：`for f in assets/*.pdf; do python publish_resource_api.py cookies.txt "$f"; done`
   跑前几条，确认每条命名/分类正确、无去重拦截。

## 8. 范围之外（本次不做）

- 不改 PPTX 原有配置流程（保持兜底可用）。
- 不自动批量上传全部 100 个（只提供单文件接口，批量由外部 shell 循环驱动）。
- 不改 classid/subject/period 等其它固定字段（除非后续要求）。
- 不清理临时目录里的上传变体文件。
