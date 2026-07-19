# 之江汇自动发布 —— 话题发布 + 置顶加精 + 教研参与留言 同步设计

- 日期：2026-07-17
- 作者：自动化助手（基于 brainstorming 流程）
- 状态：待用户审阅

## 1. 背景与目标

当前 `/Users/matthew/workshop/clock`（已部署到服务器 `124.222.39.165`，每天 06:00 跑
`run_daily.sh`）已实现：刷新 cookie（cube 登录拿 `eduyun_sessionid`）→ 上传当天资源
（Playwright）→ 微信推送（PushPlus，毛毛小主风格）。

另一分支 `/Users/matthew/workshop/clock/clock`（作者 yanhong 的 Mac 环境）额外实现了三件事：
1. 发布话题（脚本内容较当前分支更完整，含 cookie 凭据过滤）；
2. 每次发布话题时，把「洪彦」名下的旧【置顶+加精】话题撤顶+取消加精，新话题置顶+加精；
3. 参与最新的一个「未加入」教研活动，并在「提问研讨」栏留 5 条言。

**目标**：把上述三项能力同步进当前分支并接入现有 06:00 定时任务，且不破坏已验证的
cookie/资源/推送架构。

## 2. 范围

### In scope
- 新建 `publish_topic_manager.py`：发布当天话题 + 旧话题撤顶取消加精 + 新话题置顶加精。
- 复制并改造 `join_activity_and_comment.py`：教研参与 + 提问研讨留言 5 条。
- 复制 `提问研讨留言库.docx`（留言内容源）与分支版 `topics_config.json`（含 date 排期 + default）。
- 改造 `run_daily.sh`：顺序增加话题发布、教研参与两步，捕获退出码。
- 扩展 `notify.py`：增加 `--topic-status` / `--activity-status`，正文追加两行状态。
- 同步到服务器并手动验证一次全链路。

### Out of scope
- 不改动资源上传（`publish_resource_*.py`）、`refresh_cookie.py`、微信推送主文案/8 字标题。
- 不实现「遍历所有未加入活动」（仅参与最新的一个，见 §3）。
- 不覆盖当前 `refresh_cookie.py`（单数，cube 登录）；分支的 `refresh_cookies.py`（复数）不引入。
- 不做账号凭据机制变更（继续用 `.env` 的 `ZJER_USER/PASS`）。

## 3. 已澄清的需求决策

- **Q1 参与范围**：每次只参与「一个」最新的未开始且未加入的活动并留 5 条言（与分支原逻辑一致，规避风控）。
- **Q2 定时编排**：并入现有 06:00 任务（`run_daily.sh`），不单独设定时。
- **Q3 推送汇总**：保留资源主文案（毛毛小主风格）不变；话题发布、教研参与作为额外状态行追加到正文。

## 4. 方案选择

**采用方案 A（能力移植，复用当前架构）**，排除方案 B（整目录覆盖会破坏现有 cookie 机制）。
理由：当前分支的 `refresh_cookie.py` + `cookies.txt`（cube 登录态）是服务器已验证的核心，
分支靠 `cookies.txt` 内 `ACCOUNT/PASSWORD` 重登录与之冲突。移植能力、复用现有 cookie 文件最稳。

## 5. 文件变更清单

| 动作 | 文件 | 说明 |
|---|---|---|
| 新建 | `publish_topic_manager.py` | 移植分支 `studio_topic_manager.py`/`run_today.py` 的发布+置顶加精逻辑，读当前 `cookies.txt` |
| 复制+改造 | `join_activity_and_comment.py` | 复制分支版；去 `refresh_cookies` 依赖；Chrome 走 venv chromium(headless+`--no-sandbox --disable-dev-shm-usage`)；路径相对化 |
| 复制 | `提问研讨留言库.docx` | 留言内容源，置于项目根目录 |
| 覆盖 | `topics_config.json` | 采用分支版（含 date 排期 + default），供话题按当天匹配 |
| 改 | `run_daily.sh` | 顺序增加「发布话题+置顶加精」「教研参与+留言」，捕获 `TK_EXIT`/`AC_EXIT` |
| 改 | `notify.py` | 增加 `--topic-status` / `--activity-status`，正文在资源行下追加状态 |

保留：`publish_topic_api.py` / `publish_topic_playwright.py` / `refresh_cookie.py` /
`publish_resource_*.py` / `resource_config.py` / `topic_config.py` 不动。

## 6. 模块设计

### 6.1 发布话题 + 置顶加精（`publish_topic_manager.py`）
依赖：playwright（发布）+ requests（管理 API）。
流程：
1. 读 `topics_config.json`，按 `date==今天` 匹配，fallback `default`，得 `title`/`content`。
2. Playwright 进发布页，填 `#title`，UEditor `setContent`（兼容 `isReady` 永不 true 的情况，实例存在即写），点击 `#topic_butt`，从最终 URL 取新 `id`。
3. requests 扫前端列表 `studio/topic/index`，正则 `<i class='top'>置顶</i><i class='special'>精</i>...id=(\d+)` 收集置顶+加精话题；从管理列表 `studio/manage/topic/list` 取 `id→作者`，筛选作者==`洪彦`。
4. 对「洪彦的旧置顶话题（排除新 id）」批量 `manage_action(action="untop")` + `manage_action(action="unessence")`。
5. 对新 id `manage_action("top")` + `manage_action("essence")`。
6. 退出码：发布失败或置顶加精异常 → 非 0；否则 0。

管理接口：`POST studio/manage/topic/manage&sid=2174&tid=2174`，body
`YII_CSRF_TOKEN` + `ck1=逗号id` + `action∈{top,untop,essence,unessence}`，带 `X-Requested-With: XMLHttpRequest`。
CSRF 从发布页 `csrftk=` 或 cookie `YII_CSRF_TOKEN` 取。

### 6.2 教研参与 + 留言（`join_activity_and_comment.py`）
依赖：playwright + 标准库 `zipfile`（解析 docx，无需 python-docx）。
流程：
1. 进 `studio/activies/list`，点「未开始」筛选；抓 `aid=数字` 卡片，仅留状态含「未开始」的。
2. 逐个进详情 `studio/activies/activiesdetail&aid=`，查 `a[onclick*='joinact']`：
   - 无按钮 = 已参与，跳过；
   - `status==2` = 需邀请码，跳过（仍尝试留言）；
   - 否则点「立即参与」。取第一个「未开始且未加入且无需邀请码」的活动。
3. 从 `提问研讨留言库.docx` 解析留言（每段非空一行），随机取 **5 条不同**留言。
4. 在「提问研讨」栏逐条填 `placeholder*='还能输入'` 的输入框，点 `commentPublish` 提交。
5. 输出「参与成功 / 留言 x/5」；保留 `--count`/`--dry-run`/`--aid` 参数。
退出码：参与或留言全失败 → 非 0；否则 0（部分失败也尽量继续）。

### 6.3 配置与路径适配
- 所有 `/Users/yanhong/Desktop/clock/...` 硬编码改为基于 `os.path.dirname(__file__)` 的相对路径（本地 + 服务器通用）。
- Cookie：只读当前 `cookies.txt`（已由 `run_daily.sh` 第一步 `refresh_cookie.py` 刷新），不自行重登录，不 import 分支 `refresh_cookies`。
- Chrome：去掉 `executable_path`，用 venv 默认 chromium；启动参数 `headless=True, args=["--no-sandbox","--disable-dev-shm-usage"]`（与现有 `publish_resource_playwright.py` 一致，适配服务器 VM）。
- `HONGYAN_NAME="洪彦"` 保留（当前账号即洪彦，sid=2174）。

### 6.4 定时任务编排（`run_daily.sh`）
新顺序：
```
1) 刷新 cookie (refresh_cookie.py --mode playwright, cube 登录)   → CK_EXIT
2) 上传资源   (publish_resource_playwright.py --mode auto)        → UP_EXIT
3) 发布话题+置顶加精 (publish_topic_manager.py)                   → TK_EXIT  (新增)
4) 教研参与+留言   (join_activity_and_comment.py)                → AC_EXIT  (新增)
5) 微信推送   (notify.py 传入 CK/UP/TK/AC 四态)                  → 成败都推
```
各步独立捕获退出码；任一步失败不影响后续步骤（与现有资源步骤一致）。

### 6.5 微信推送扩展（`notify.py`）
- 新增参数 `--topic-status`、`--activity-status`（默认「未知」）。
- 正文在「资源上传」描述行下追加：
  - `话题发布：成功/失败 (exit=...)`
  - `教研参与：成功(留言 x/5)/失败`
- 主文案（毛毛小主资源句式）、8 字短标题（`毛毛小主下发完毕`/`毛毛小主推送卡壳`）、antd 卡片头（`毛毛打卡通知`）保持不变。
- `run_daily.sh` 第 5 步构造四态传入。

## 7. 错误处理
- 话题发布失败：打印响应片段，`TK_EXIT≠0`，但继续教研参与与推送（不中断全任务）。
- 置顶加精异常：catch 后继续，不影响已发布话题；记日志。
- 教研参与需邀请码/已参与：跳过该活动，仍尝试留言；留言部分失败计数后继续。
- cookie 失效：`run_daily.sh` 第 1 步已重刷；后续步骤若 403 则对应退出码非 0，推送如实反映。
- 留言库不足 5 条：全量使用，提示数量。

## 8. 测试 / 验证
- 本地语法检查 + `join_activity_and_comment.py --dry-run` 预览（不实际操作）。
- 服务器手动跑一次 `bash run_daily.sh`，确认四步均执行、退出码合理。
- 微信收到推送，正文含「话题发布」「教研参与」两行状态。
- 登录之江汇工作室后台肉眼确认：新话题已置顶+加精，旧洪彦话题已撤顶；教研活动已参与且提问研讨有 5 条新留言。

## 9. 风险与注意
- 平台风控：教研留言为随机 5 条/天，频率低，风险可控；不遍历所有活动。
- 置顶加精仅操作「洪彦」话题，不影响他人。
- 服务器已装 venv chromium（资源上传验证过），教研脚本复用同一环境。
- `topics_config.json` 覆盖为分支版，会带入分支的 date 排期；若与当前 `topic_config.py` 加载器不兼容，以 `publish_topic_manager.py` 自带加载逻辑为准（移植分支 `load_topic_config`）。
