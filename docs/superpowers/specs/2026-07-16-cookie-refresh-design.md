# 设计文档：之江汇 Cookie 自动刷新工具

- 日期：2026-07-16
- 项目：之江汇教育广场（ms.zjer.cn 陈晓雯名师工作室 sid=2174）自动发布
- 产物：`refresh_cookie.py`（新增脚本）

## 1. 背景与目标

现有 4 个发布脚本（话题/资源 × 接口版/Playwright 版）依赖 `cookies.txt` 里的登录态。
登录态会过期，目前只能手工从浏览器拷 Cookie。本设计新增一个脚本，自动完成：

**登录 → 取 Cookie → 序列化 → 覆盖 `cookies.txt`**

覆盖前自动备份；登录或校验失败则**不覆盖**旧 Cookie，避免刷新翻车丢登录态。

### 关键上下文（已确认）
- `cookies.txt` 是单行 `name=value; name=value` 串，被接口版直接当 `Cookie` 请求头用，
  被 Playwright 版 `parse_cookies()` 拆成单条 cookie 注入 context。
- 用户提供的登录入口是**互联网学校**（`szyx.zjer.cn`）的授权流：
  `https://szkj.zjer.cn/hlwxx/webAuthorize?redirect_url=https%3A%2F%2Fszyx.zjer.cn%2Fmicro%2Fweb%2FinternetSchool%2Flogin%3Fredirect%3Dhttps%3A%2F%2Fszyx.zjer.cn%2Fmicro%2Fweb%2FinternetSchool`
- 该登录流与现有 `ms.zjer.cn` 名师工作室发布共用 SSO（`eduyun_sessionid` 等共享），
  **刷新后直接覆盖同一份 `cookies.txt`**（用户已确认）。
- 登录为「我是教师」tab + 账号密码 + 阅读同意勾选 + 登录按钮，**无图形验证码、无短信/滑块/2FA**
  （用户已确认），故 Playwright 可全 headless 自动，纯 API 也可能可行。
- 凭据通过环境变量 `ZJER_USER` / `ZJER_PASS` 传入（用户已确认），绝不落盘、不进 git。

## 2. 两种实现方式

| 方式 | 做法 | 优点 | 风险 |
|---|---|---|---|
| **Playwright 模式**（默认） | 真实浏览器打开 webAuthorize → 点「我是教师」→ 填账密 → 勾同意 → 点登录 → `context.cookies()` 取全量 | 最稳，能跑完 JS 重定向链与 SSO | 依赖 Chromium，启动慢几秒 |
| **纯 API 模式** | `requests` 复刻登录（GET 拿 csrf → POST 账密 → 跟重定向收 Set-Cookie） | 无浏览器依赖、最快、可进 cron | 站点若用 JS 生成的隐藏 token / 多步状态则难复刻，较脆 |

**推荐路线**：先写 Playwright 模式（可靠），并在其中**抓出登录那一刻的真实请求**
（URL / 方法 / 请求头 / 请求体 / 响应 Set-Cookie），据此把纯 API 模式 port 出来。
API 模式跑通即作为轻量备选；跑不通则保留 Playwright 当主用。两者都交付，Playwright 保底。

## 3. 脚本接口（沿用项目现有风格）

```bash
# 默认 Playwright 模式
ZJER_USER=hzyh2508192 ZJER_PASS='Hy53465927!' python3 refresh_cookie.py

# 纯 API 模式（Playwright 探查确认可行后启用）
ZJER_USER=... ZJER_PASS=... python3 refresh_cookie.py --mode api

# 调试：弹出真实浏览器看过程
python3 refresh_cookie.py --no-headless
```

- 位置参数 `cookie`（可选，默认脚本同目录的 `cookies.txt`）：既是输入（登录失败时不依赖它），也是输出落盘路径。
- `--mode {playwright,api}`，默认 `playwright`。
- `--no-headless`：Playwright 弹窗可视化（默认 headless）。

## 4. 公共流程

```
读 env 凭据 (ZJER_USER / ZJER_PASS)
  → 备份 cookies.txt → cookies.txt.<timestamp>.bak
  → 按 --mode 获取 Cookie
  → 序列化为 "name=val; name=val" 单行串（与现有格式完全一致）
  → 写回 cookies.txt
  → 校验（用新 Cookie GET 受保护页）
  → 成功✅ / 失败❌（保留旧 Cookie，退出码非 0）
```

序列化：`"; ".join(f"{c['name']}={c['value']}" for c in cookies)`。
现有 4 个发布脚本读取格式不变，零改动即可复用新 Cookie。

## 5. Playwright 模式要点

- `p.chromium.launch(headless=..., args=["--no-sandbox"])`，`user_agent=UA`（沿用现有 UA 常量）。
- 常量 `WEB_AUTH_URL = "https://szkj.zjer.cn/hlwxx/webAuthorize?redirect_url=https%3A%2F%2Fms.zjer.cn%2Findex.php%3Fr%3Dstudio%2Findex%2Findex%26sid%3D2174"`（落到**名师工作室**首页，刷新出发布必需的 `ck_ms`）。
- **实现修正（2026-07-16 实测）**：原设想的 `redirect_url=...szyx.zjer.cn/...` 只落到互联网学校 app，下发 `WEB_MicroDigitalAccessToken`、**不含 `ck_ms`**，不能用于 ms.zjer.cn 发布。改为指向 ms.zjer.cn 工作室落地页后才正确产出 `ck_ms`。`AUTH_MARKERS` 因此收紧为仅 `("ck_ms",)`，且 `verify_cookie` 以「含 ck_ms」为决定性判据（ms.zjer.cn 话题页是 SPA，静态 HTML 无法判定登录态）。
- `page.goto(WEB_AUTH_URL, wait_until="domcontentloaded")`。
- 点「我是教师」tab：按可见文本定位（div/li/a 含「我是教师」），超时 10s。
- 填账号 / 密码输入框（先按 placeholder/name 试探，失败再按可见标签定位）。
- **勾选「阅读同意」**：用点 label 的方式（参考资源脚本里点「承诺」checkbox 的兜底——
  先 `click(input[type=checkbox])`，失败再点包含「阅读」「同意」文字的 `label`，
  再失败 `evaluate` 设 `checked=true` 并补 `checked` class），避免纯改 `checked` 不生效。
- 点「登录」按钮（按可见文字「登录」定位）。
- 等重定向稳定（`wait_for_load_state("networkidle")` 或固定 `wait_for_timeout`），再 `context.cookies()` 取全部
  （都是 zjer/henan 域，无无关 cookie）。
- **探活**：在 `page.on("request")` 里捕获登录 POST，打印其 URL / 方法 / 请求头 / 请求体，
  供 API 模式 port 使用（仅日志，不影响主流程）。

## 6. 纯 API 模式要点（依赖上面探到的请求）

- `requests.Session()`。
- `GET` 授权页：收会话 Cookie，解析可能的 `_csrf` / 隐藏 token。
- `POST` 登录接口：带账密 + 同意参数；Session 自动收 `Set-Cookie` 并跟重定向（含 szkj → yun.zjer.cn eduyun 会话 → szyx 的 SSO 链）。
- 从 `session.cookies` 拼出单行串。
- 若探到需要 JS 才有的隐藏字段 / 多步状态，则代码内明确标注「此站纯 API 不可行」，
  并给出降级提示（改用 `--mode playwright`）。

## 7. 错误处理与校验（关键安全点）

- 登录失败（页面出现「账号或密码错误」等关键字，或 API 返回非预期）→ **中止、不写** cookies.txt，旧 Cookie 保留，退出码非 0。
- 写完做**校验 GET**：用新 Cookie 请求 `ms.zjer.cn` 的受保护页（如话题发布页 `index.php?r=studio/topic/add&sid=2174`）。
  - 返回 200 且未被重定向到登录页 → ✅ 成功（SSO 互通确认）。
  - 被重定向到登录页 → ⚠️ 警告「SSO 可能未覆盖 ms.zjer.cn」，但仍保留新 Cookie 供 szyx 使用，并提示用户。
- 备份文件命名带时间戳，便于回滚。

## 8. 落盘与安全

- 覆盖前 `cookies.txt` → `cookies.txt.<timestamp>.bak`。
- 凭据只走环境变量，不落盘、不进 git。
- `cookies.txt` 为敏感物，遵循 README 既有约定「切勿提交」。脚本本体可提交，但绝不提交任何含密码的文件。

## 9. 验收标准

- 跑 Playwright 模式：`cookies.txt` 被更新，`ck_ms` / `eduyun_sessionid` 等字段刷新；
  用现有 `publish_topic_api.py cookies.txt` 能成功发一条话题（端到端验证 SSO 互通）。
- 跑 API 模式（若可行）：同上端到端验证。
- 故意用错误密码：脚本报错、保留旧 Cookie、退出码非 0。
- 备份文件在每次覆盖前生成。

## 10. 范围之外（YAGNI）

- 不做多账号 / 多工作室管理。
- 不做定时调度（如需可后续加 automation，不在本 spec）。
- 不解析或展示 Cookie 内容明细（只序列化落盘 + 必要校验）。
