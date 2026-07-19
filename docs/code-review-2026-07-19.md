# 代码 Review 报告 — `src/config/data` 分层重组

- **日期**：2026-07-19
- **范围**：扁平 → 分层重组后的全部代码（`src/` 15 py、`config/` 2 json、`data/`、`legacy/` 11 py、根目录 3 个 sh）
- **方法**：静态路径/import 扫描 + 服务器端端到端验证（资源上传跑通、文章 dry-run、cron 探针）

---

## 一、重组核心质量：✅ 通过

本次改造最关键的是「路径重定位正确性」。所有数据/配置引用均已改为 `HERE/..`（HERE=`src/`，上级=项目根），**无遗漏**：

| 引用目标 | 文件:行 |
|---|---|
| `cookies.txt` | `publish_article_playwright.py:32`、`join_activity_and_comment.py:26`、`publish_topic_manager.py:19`、`check_article.py:9`、`refresh_cookie.py:30` |
| `data/articles` | `publish_article_playwright.py:33` |
| `data/assets` | `split_upload_daily.py:37`、`publish_resource_api.py:228`、`publish_resource_playwright.py:91`、`rename_assets.py:15` |
| `config/*.json` | `topic_config.py:31`、`resource_config.py:165` |
| `.env` | `refresh_cookie.py:54`、`notify.py:142` |

- 3 个 sh **全部**以 `src/` 前缀调用（`run_daily.sh` / `publish_article_daily.sh` / `split_upload_daily.sh` 共 12 处 `.py` 调用）。
- 跨模块 import（`topic_config` / `resource_config` / `publish_article_playwright`）同处 `src/`，sh 用 `python src/x.py` 使 `sys.path[0]=src/`，工作正常（dry-run 已验证）。
- `crontab` 三条任务不变（仍指向根目录 sh），零改动即上线。
- 服务器端已端到端验证：资源上传跑通、文章/拆页 dry-run 读到新路径、cron 探针 mtime=21:12:01 证明自动触发正常。

---

## 二、发现的问题

### Important（建议修）

**I-1. `legacy/` 脚本数据路径已过时**
`imslp_fetch.py:37`、`fetch_tan8.py:33`、`gen_scores.py:17` 均为 `ASSETS = os.path.join(HERE, "assets")` → 指向 `legacy/assets/`，而实际资源在 `data/assets/`。重跑这些一次性抓取脚本会写到错误目录。
- 附加：`probe_batch.py:4` 硬编码 `sys.path.insert(0, "/Users/matthew/workshop/clock")` 绝对路径，换机/移动即失效。
- 影响：仅 `legacy/` 归档脚本；cron 不调用，**不影响生产链路**。

**I-2. 跨模块 import 依赖隐式 `sys.path`**
`publish_resource_api.py:32`、`publish_topic_api.py:22`、`publish_topic_playwright.py:24`、`check_article.py:4` 用 `from xxx import ...`。目前因 sh 调用方式稳定而工作，但若 `python -m src.x` 或根目录直接运行会 `ImportError`。建议每个脚本顶部显式 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`（`tests/` 已这样做）。

**I-3. `.gitignore` 过窄**
仅忽略 `.env` / `cookies.txt` / `cookies.*.bak`。未忽略：`__pycache__/`、`*.pyc`、`*.log`（cron.log 等）、`.DS_Store`、调试产物（`article_debug.html` / `article_resp.txt` / `article_debug.txt` / `article_whitebox.png`）、`data/assets/_pages/`（拆页产物）、`clock_backup_*`、`.cron_probe`。将来若 `git init` 会污染版本库/泄露敏感。

### Minor（可后处理）

**M-4. 调试产物写入 `src/` 源码目录**
`publish_article_playwright.py:232/277/315/316` 把 `whitebox.png` / `resp.txt` / `debug.html` / `debug.txt` 写到 `HERE=src/`。失败时会重新污染 `src/`，且 `.gitignore` 未忽略。建议改到 `data/` 下 debug 区或 `tempfile`。

**M-5. 本地根目录 `.DS_Store` 残留**
服务器因 rsync `--exclude='.DS_Store'` 未同步，但本地有。应删并纳入 `.gitignore`。

**M-6. 子进程输出非实时**
`split_upload_daily.py:143-144` 用 `PIPE` 收集，上传完成才一次性打印到 `cron.log`。cron 期间日志不刷新，排障看不到进度（此前你提过「日志可读性差」）。

**M-7. `split_upload_daily.py:103` `os.chdir(HERE)` 脆弱模式**
当前安全（所有路径用绝对 `HERE`、子进程 `cwd=HERE` 且用 `src/` 内脚本名），但属脆弱写法——将来在 `chdir` 后新增相对路径构造会静默指向 `src/`。建议移除 `chdir` 或全程用绝对路径。

---

## 三、结论

重组**核心正确、可上线**。Important 项均不影响当前 cron 生产链路（已逐项验证），但 `legacy` 路径 / `.gitignore` / import 稳健性属于「清理代码」应顺手收尾的范围；Minor 项以 M-4（源码目录污染）优先级最高。

## 四、修复记录（2026-07-19 已执行，用户选「全部修复」）

- **I-3** `.gitignore` 补全：`__pycache__/`、`*.pyc`、`*.log`、`.DS_Store`、调试产物、`data/_debug/`、`data/assets/_pages/`、`clock_backup_*`、`.cron_probe`。
- **I-1** `legacy/` 三脚本 `ASSETS` 改 `HERE/../data/assets`；`probe_batch.py` 硬编码绝对路径改 `sys.path.insert(0, os.path.dirname(__file__))`。
- **I-2** `publish_resource_api/topic_api/topic_playwright/check_article` 顶部加 `sys.path.insert(0, os.path.dirname(__file__))` 显式化同目录 import。
- **M-4** `publish_article_playwright` 调试产物(`whitebox.png`/`resp.txt`/`debug.html`/`debug.txt`)改写 `data/_debug/`。
- **M-5** 删除本地根目录 `.DS_Store`。
- **M-6** `split_upload_daily.py` 上传子进程改 `Popen` 逐行实时 `flush` 输出（cron 日志实时可见）。
- **M-7** `split_upload_daily.py` 移除 `os.chdir(HERE)`，子进程脚本名改 `HERE` 绝对路径。

**验证**：本地+服务器 `py_compile` 全过；文章/拆页 dry-run 读新路径正常；服务器真实上传(`--no-notify`) 成功 3/失败 0、实时日志可见、`exit=0`；cron 三条任务未改动。已 rsync 同步服务器。
