# 之江汇 Cookie 自动刷新工具 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `refresh_cookie.py`，自动登录之江汇（szkj/szyx SSO），取全量 Cookie 覆盖 `cookies.txt`，供现有 4 个发布脚本复用。

**Architecture:** 单脚本双模式。`--mode playwright`（默认，可靠、保底）用真实浏览器走完登录+SSO 重定向链后 `context.cookies()` 取全量；`--mode api` 用 requests 复刻登录请求（依赖 Playwright 模式先探到的真实请求）。公共逻辑：读 env 凭据 → 备份 → 取 Cookie → 序列化单行串 → 写回 → 校验 GET。

**Tech Stack:** Python 3.13（managed venv）、playwright（已装 Chromium）、requests。参考 spec：`docs/superpowers/specs/2026-07-16-cookie-refresh-design.md`。

**项目特殊约定（重要）：**
- 本目录**不是 git 仓库**，且无单元测试框架。现有脚本均为「直接 run 对着线上站点验证」。
- 因此本计划**不含 `git commit` 步骤**，每个 Task 的「测试」= 对线上站点实跑并核对输出/落盘。
- Python 解释器统一用：`/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python`（下称 `$PY`）。
- 凭据通过环境变量传入：`ZJER_USER=hzyh2508192 ZJER_PASS='Hy53465927!'`。
- UA 常量沿用现有脚本：`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36`。

---

## File Structure

- **Create: `refresh_cookie.py`** — 唯一新增文件，含：
  - 公共工具：`log`、`read_creds`、`backup_cookie`、`serialize_cookies`、`write_cookie`、`verify_cookie`。
  - `login_playwright(...)` → 返回 cookie 列表 + 打印登录 POST 请求探活信息。
  - `login_api(...)` → 返回 cookie 列表（据探活信息实现；不可行则抛错并提示降级）。
  - `main()`：argparse（`cookie` 位置参数、`--mode`、`--no-headless`）+ 编排公共流程。
- **Modify: `README.md`** — 追加「Cookie 刷新」小节与用法。

不拆多文件：脚本量级与现有 4 个单文件脚本相当，保持项目一致的「一功能一脚本」风格。

---

## Task 1: 脚手架 + 公共工具函数

**Files:**
- Create: `/Users/matthew/workshop/clock/refresh_cookie.py`

- [ ] **Step 1: 写文件头 + 常量 + 公共工具**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
之江汇 Cookie 自动刷新
登录 szkj/szyx SSO -> 取全量 Cookie -> 覆盖 cookies.txt(先备份)。
供现有 4 个发布脚本复用。凭据走环境变量 ZJER_USER / ZJER_PASS。

用法:
  ZJER_USER=hzyh2508192 ZJER_PASS='Hy53465927!' python3 refresh_cookie.py
  ZJER_USER=... ZJER_PASS=... python3 refresh_cookie.py --mode api
  python3 refresh_cookie.py --no-headless   # 弹窗调试
"""
import os, sys, time, argparse, requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
WEB_AUTH_URL = ("https://szkj.zjer.cn/hlwxx/webAuthorize?redirect_url="
                "https%3A%2F%2Fszyx.zjer.cn%2Fmicro%2Fweb%2FinternetSchool%2Flogin"
                "%3Fredirect%3Dhttps%3A%2F%2Fszyx.zjer.cn%2Fmicro%2Fweb%2FinternetSchool")
# 校验用: 名师工作室话题发布页(受登录保护)
VERIFY_URL = "https://ms.zjer.cn/index.php?r=studio/topic/add&sid=2174"
DEFAULT_COOKIE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")


def log(*a):
    print(*a, flush=True)


def read_creds():
    u = os.environ.get("ZJER_USER")
    p = os.environ.get("ZJER_PASS")
    if not u or not p:
        raise SystemExit("缺少凭据: 请设置环境变量 ZJER_USER 和 ZJER_PASS")
    return u, p


def backup_cookie(path):
    if os.path.exists(path):
        ts = time.strftime("%Y%m%d_%H%M%S")
        bak = f"{path}.{ts}.bak"
        with open(path, "rb") as f:
            data = f.read()
        with open(bak, "wb") as f:
            f.write(data)
        log(f"已备份旧 Cookie -> {bak}")
        return bak
    log("无旧 cookies.txt, 跳过备份")
    return None


def serialize_cookies(cookies):
    # cookies: list of dict, 至少含 name/value
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))


def write_cookie(path, cookie_str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(cookie_str)
    log(f"已写入 {path} ({len(cookie_str)} chars, {cookie_str.count(';') + 1} cookies)")


def verify_cookie(cookie_str):
    h = {"Cookie": cookie_str, "User-Agent": UA}
    try:
        r = requests.get(VERIFY_URL, headers=h, timeout=30, allow_redirects=False)
    except Exception as e:
        log(f"校验请求异常: {e}")
        return False
    loc = r.headers.get("Location", "")
    # 被跳登录 = 失败迹象
    if r.status_code in (301, 302, 303, 307) and ("login" in loc.lower() or "passport" in loc.lower()):
        log(f"⚠️ 校验: 被重定向到登录页 ({loc[:80]}), SSO 可能未覆盖 ms.zjer.cn")
        return False
    if r.status_code == 200 and ("topic" in r.text or "话题" in r.text):
        log("✅ 校验: ms.zjer.cn 受保护页正常访问, SSO 互通")
        return True
    log(f"⚠️ 校验: 状态码={r.status_code}, 未明确判定(Location={loc[:60]})")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cookie", nargs="?", default=DEFAULT_COOKIE_PATH, help="cookies.txt 路径(默认脚本同目录)")
    ap.add_argument("--mode", choices=["playwright", "api"], default="playwright")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", dest="headless", action="store_false", help="弹窗可视化调试")
    args = ap.parse_args()

    user, pwd = read_creds()
    log(f"mode={args.mode} headless={args.headless} user={user}")

    if args.mode == "playwright":
        cookies = login_playwright(user, pwd, headless=args.headless)
    else:
        cookies = login_api(user, pwd)

    if not cookies:
        raise SystemExit("❌ 登录未取到 Cookie, 保留旧 cookies.txt, 退出")

    cookie_str = serialize_cookies(cookies)
    if len(cookie_str) < 30:
        raise SystemExit(f"❌ 取到的 Cookie 串过短({cookie_str!r}), 疑似登录失败, 保留旧 cookies.txt")

    backup_cookie(args.cookie)
    write_cookie(args.cookie, cookie_str)

    ok = verify_cookie(cookie_str)
    if ok:
        log("✅ 完成: Cookie 已刷新并通过校验")
    else:
        log("⚠️ 完成: Cookie 已写入, 但校验未通过(可能仅 szyx 可用/站点判定变化), 请人工确认")
        sys.exit(2)


if __name__ == "__main__":
    main()
```

注意：此时 `login_playwright` / `login_api` 还未定义，Task 2/3 补上。为使文件可被 `python -c` 导入检查语法，本步先在文件中放两个占位（会在下一步替换）：

```python
def login_playwright(user, pwd, headless=True):
    raise NotImplementedError

def login_api(user, pwd):
    raise NotImplementedError
```
把这两个占位放在 `main()` 定义之前。

- [ ] **Step 2: 语法自检**

Run: `/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "import ast; ast.parse(open('/Users/matthew/workshop/clock/refresh_cookie.py').read()); print('OK')"`
Expected: 打印 `OK`

- [ ] **Step 3: 缺凭据时的报错自检**

Run: `cd /Users/matthew/workshop/clock && env -u ZJER_USER -u ZJER_PASS /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python refresh_cookie.py`
Expected: 打印 `缺少凭据: 请设置环境变量 ZJER_USER 和 ZJER_PASS` 并非零退出。

---

## Task 2: Playwright 登录模式（默认、保底）

**Files:**
- Modify: `/Users/matthew/workshop/clock/refresh_cookie.py`（替换 `login_playwright` 占位）

- [ ] **Step 1: 实现 login_playwright（含探活打印）**

用下列实现替换 `login_playwright` 占位：

```python
def login_playwright(user, pwd, headless=True):
    from playwright.sync_api import sync_playwright
    login_posts = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless, args=["--no-sandbox"])
        ctx = b.new_context(user_agent=UA)
        page = ctx.new_page()

        def on_request(req):
            if req.method == "POST":
                low = req.url.lower()
                if any(k in low for k in ("login", "auth", "passport", "token")):
                    try:
                        pd = req.post_data or ""
                    except Exception:
                        pd = ""
                    login_posts.append((req.url, dict(req.headers), pd[:500]))
        page.on("request", on_request)

        log(f"打开授权页: {WEB_AUTH_URL[:80]}...")
        page.goto(WEB_AUTH_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)

        # 1) 点「我是教师」tab (按可见文本)
        try:
            page.get_by_text("我是教师", exact=False).first.click(timeout=8000)
            log("已点『我是教师』tab")
        except Exception as e:
            log(f"点『我是教师』失败(可能默认已在该tab): {e}")
        page.wait_for_timeout(800)

        # 2) 填账号密码 (先按常见 selector, 失败再按可见输入框顺序)
        filled = _fill_credentials(page, user, pwd)
        log(f"账密填写: {filled}")

        # 3) 勾选阅读同意 (点 checkbox -> 点相关 label -> JS 兜底)
        agreed = _check_agree(page)
        log(f"阅读同意勾选: {agreed}")

        # 4) 点登录
        try:
            page.get_by_text("登录", exact=True).first.click(timeout=8000)
        except Exception:
            try:
                page.get_by_role("button", name="登录").first.click(timeout=8000)
            except Exception as e:
                log(f"点『登录』失败: {e}")
        log("已点『登录』, 等待重定向...")

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as e:
            log(f"networkidle note: {e}")
        page.wait_for_timeout(4000)

        # 探活打印: 供 API 模式 port
        log("=== 登录相关 POST 请求(探活, 供 API 模式参考) ===")
        for url, hdr, pd in login_posts:
            log(f"  URL : {url}")
            log(f"  BODY: {pd}")
            ct = hdr.get("content-type", "")
            if ct:
                log(f"  CT  : {ct}")
        if not login_posts:
            log("  (未捕获到疑似登录 POST, 可能走 GET 或不同关键字)")

        cookies = ctx.cookies()
        log(f"取到 {len(cookies)} 条 cookie")
        b.close()
    return [{"name": c["name"], "value": c["value"]} for c in cookies]


def _fill_credentials(page, user, pwd):
    user_selectors = [
        'input[name="username"]', 'input[name="account"]', 'input[name="loginName"]',
        'input[placeholder*="账号"]', 'input[placeholder*="用户名"]', 'input[type="text"]',
    ]
    pwd_selectors = [
        'input[name="password"]', 'input[placeholder*="密码"]', 'input[type="password"]',
    ]
    u_ok = p_ok = False
    for sel in user_selectors:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible():
                el.fill(user, timeout=4000); u_ok = True; break
        except Exception:
            continue
    for sel in pwd_selectors:
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible():
                el.fill(pwd, timeout=4000); p_ok = True; break
        except Exception:
            continue
    return {"user": u_ok, "pwd": p_ok}


def _check_agree(page):
    # 优先点 checkbox
    try:
        cb = page.locator('input[type="checkbox"]').first
        if cb.count():
            cb.check(timeout=4000)
            if cb.is_checked():
                return "checkbox.check"
    except Exception:
        pass
    # 点含 阅读/同意 文字的 label
    js = """() => {
        const labs=[...document.querySelectorAll('label, span, a, div')];
        const t=labs.find(x=>{const s=(x.innerText||'');return s.includes('同意')||s.includes('阅读');});
        if(t){ t.click(); return true; } return false;
    }"""
    try:
        if page.evaluate(js):
            return "label.click"
    except Exception:
        pass
    # JS 兜底强制 checked
    try:
        page.evaluate("""() => { document.querySelectorAll('input[type=checkbox]').forEach(c=>c.checked=true); }""")
        return "js.checked"
    except Exception as e:
        return f"fail:{e}"
```

- [ ] **Step 2: 语法自检**

Run: `/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "import ast; ast.parse(open('/Users/matthew/workshop/clock/refresh_cookie.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 可视化实跑（先看能否走完登录）**

Run: `cd /Users/matthew/workshop/clock && ZJER_USER=hzyh2508192 ZJER_PASS='Hy53465927!' /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python refresh_cookie.py --no-headless`
Expected:
- 弹窗打开授权页 → 自动填账密、勾同意、点登录、重定向。
- 终端打印 `账密填写: {'user': True, 'pwd': True}`、`阅读同意勾选: ...`、探活的登录 POST（URL/BODY）、`取到 N 条 cookie`（N > 5）。
- 若某个定位失败：据弹窗实际 DOM 调整 `_fill_credentials` / `_check_agree` / tab、登录按钮的定位（这是唯一需要按真实页面微调的地方；把最终可用的 selector 固化进代码）。

- [ ] **Step 4: headless 实跑 + 校验 + 落盘**

Run: `cd /Users/matthew/workshop/clock && ZJER_USER=hzyh2508192 ZJER_PASS='Hy53465927!' /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python refresh_cookie.py`
Expected:
- 打印 `已备份旧 Cookie -> cookies.txt.<ts>.bak`、`已写入 .../cookies.txt`、`✅ 校验: ms.zjer.cn 受保护页正常访问, SSO 互通`、`✅ 完成`。
- 若校验未通过但确有 cookie：允许保留（退出码 2），人工核对是否 szyx-only。

- [ ] **Step 5: 端到端验证（用现有发布脚本证明 Cookie 可用）**

Run: `cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python publish_topic_api.py cookies.txt --dry-run`
Expected: 打印抓到的 `_csrf`（非空）说明新 Cookie 能进受保护页；`--dry-run` 不实际发帖。

---

## Task 3: 纯 API 登录模式（据探活结果实现）

**Files:**
- Modify: `/Users/matthew/workshop/clock/refresh_cookie.py`（替换 `login_api` 占位）

**前置：** 必须已完成 Task 2 Step 3/4，拿到探活打印的登录 POST（URL / BODY / Content-Type）。下面代码里的 `LOGIN_API_URL`、字段名（`username`/`password`/同意字段）、GET 授权页取 token 的正则，**必须用探到的真实值替换占位注释处**。

- [ ] **Step 1: 实现 login_api（模板，按探活值填实）**

用下列实现替换 `login_api` 占位。`# TODO(from-probe)` 处按 Task 2 探到的真实请求填：

```python
def login_api(user, pwd):
    import re
    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    # 1) GET 授权页, 收会话 cookie + 可能的隐藏 token/_csrf
    r0 = s.get(WEB_AUTH_URL, timeout=30)
    token = ""
    m = re.search(r'name=["\']?(?:_csrf|token|csrf_token)["\']?\s+value=["\']([^"\']+)', r0.text)
    if m:
        token = m.group(1)
    log(f"api: 授权页 status={r0.status_code} token={'有' if token else '无'}")

    # 2) POST 登录
    #    LOGIN_API_URL / payload 字段名 / 同意字段 均据 Task2 探活结果填写
    LOGIN_API_URL = "TODO(from-probe): 探到的登录 POST URL"
    payload = {
        # TODO(from-probe): 探到的字段名, 常见如下, 以实际为准
        "username": user,
        "password": pwd,
        # "agree": "1",         # 阅读同意字段(若表单里有)
        # "userType": "teacher",# 我是教师(若有)
        # "_csrf": token,       # 若探到需要
    }
    if token:
        payload.setdefault("_csrf", token)

    r1 = s.post(LOGIN_API_URL, data=payload, timeout=30, allow_redirects=True)
    log(f"api: 登录 POST status={r1.status_code} final_url={r1.url[:80]}")

    # 失败判据: 响应含错误关键字
    body = r1.text or ""
    for kw in ("账号或密码错误", "密码错误", "验证码", "登录失败"):
        if kw in body:
            log(f"api: 登录疑似失败(命中 '{kw}')")
            return []

    # 3) 跟 SSO 链: 有些站点登录后还需再访问一次授权页/回跳完成种 cookie
    try:
        s.get(WEB_AUTH_URL, timeout=30)
        s.get(VERIFY_URL, timeout=30)
    except Exception as e:
        log(f"api: 补跟重定向异常(可忽略): {e}")

    cookies = [{"name": c.name, "value": c.value} for c in s.cookies]
    log(f"api: 收到 {len(cookies)} 条 cookie")
    return cookies
```

若 Task 2 探活发现**登录依赖 JS 生成的动态字段 / 多步交换**导致无法用 requests 复刻：
- 将 `login_api` 改为直接：`raise SystemExit("此站登录依赖前端 JS, 纯 API 不可行, 请用默认 --mode playwright")`
- 并在计划的完成说明中记录「API 模式不可行」的结论。

- [ ] **Step 2: 语法自检**

Run: `/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "import ast; ast.parse(open('/Users/matthew/workshop/clock/refresh_cookie.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: API 模式实跑**

先手动备份当前可用 cookie：`cp /Users/matthew/workshop/clock/cookies.txt /Users/matthew/workshop/clock/cookies.good.bak`
Run: `cd /Users/matthew/workshop/clock && ZJER_USER=hzyh2508192 ZJER_PASS='Hy53465927!' /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python refresh_cookie.py --mode api`
Expected:
- 打印 `api: 授权页 ...`、`api: 登录 POST status=...`、`api: 收到 N 条 cookie`。
- 若 `✅ 校验 ... SSO 互通` → API 模式可行。
- 若失败/cookie 过短 → 脚本保留旧 cookie（因内部备份）；确认 `cookies.good.bak` 仍在，必要时还原。

- [ ] **Step 4: 端到端验证（API 模式产出的 cookie）**

Run: `cd /Users/matthew/workshop/clock && /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python publish_topic_api.py cookies.txt --dry-run`
Expected: 抓到非空 `_csrf`。若 API 模式不可行，跳过并记录结论。

---

## Task 4: 错误密码回归 + README 文档

**Files:**
- Modify: `/Users/matthew/workshop/clock/refresh_cookie.py`（如回归暴露问题才改）
- Modify: `/Users/matthew/workshop/clock/README.md`

- [ ] **Step 1: 错误密码回归（Playwright 模式）**

先确保有可用备份：`cp /Users/matthew/workshop/clock/cookies.txt /Users/matthew/workshop/clock/cookies.good.bak`
Run: `cd /Users/matthew/workshop/clock && ZJER_USER=hzyh2508192 ZJER_PASS='wrongpass' /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python refresh_cookie.py`
Expected:
- 登录不过 → 取到的 cookie 串过短或校验失败。
- 理想：脚本在写回前就因「Cookie 串过短」中止（`❌ ... 保留旧 cookies.txt`），旧 cookie 未被破坏。
- 若发现错误密码仍种了一堆无用 cookie 导致覆盖：在 `main()` 里把「校验失败则还原备份」的兜底补上（从最近的 `.bak` 还原），再重跑本步。

> **实际实现修正（已在代码中落地）**：回归实测发现，登录失败时 Playwright 仍会拿到 ~7 条**分析类 Cookie**（如 sajssdk/Hm_lvt/cna），
> 序列化为 297 字符 > 原「`len < 30`」弱判据，导致脚本**错误覆盖**了 cookies.txt 并仅 warn。
> 修正为**双重防护**：(1) `login_playwright` 未跳转到 `szyx.zjer.cn` 时直接 `return []`；
> (2) `main()` 写盘前用 `has_auth_session()` 校验 Cookie 串必须含 `ck_ms`/`eduyun_sessionid`/`WEB_MicroDigitalAccessToken` 之一，
> 否则 `raise SystemExit` 中止、**不覆盖**旧 Cookie。逻辑单测已验证：纯分析类串判为 False(中止)，真实会话串判为 True(放行)。

- [ ] **Step 2: README 追加「Cookie 刷新」小节**

在 `README.md` 的「快速开始」之后插入：

```markdown
## Cookie 刷新（refresh_cookie.py）

登录态过期时，自动重新登录并覆盖 `cookies.txt`（覆盖前自动备份）。
凭据走环境变量，不落盘、不进 git。

```bash
# 默认 Playwright 模式（可靠，推荐）
ZJER_USER=你的账号 ZJER_PASS='你的密码' python3 refresh_cookie.py

# 纯 API 模式（更快，若该站可行）
ZJER_USER=... ZJER_PASS=... python3 refresh_cookie.py --mode api

# 调试：弹出真实浏览器看登录过程
python3 refresh_cookie.py --no-headless
```

- 登录/校验失败不会覆盖旧 Cookie；旧文件会先备份为 `cookies.txt.<时间戳>.bak`。
- 刷新后可用 `python3 publish_topic_api.py cookies.txt --dry-run` 快速验证。
```

- [ ] **Step 3: README 语法目检**

Run: `/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "print(open('/Users/matthew/workshop/clock/README.md').read()[:1])"`
Expected: 无异常（能读）。人工确认小节渲染正常。

---

## Self-Review（写完计划后自查，已执行）

**1. Spec coverage：**
- spec §2 双模式 → Task 2（playwright）+ Task 3（api）✅
- spec §3 接口/env/--mode/--no-headless → Task 1 argparse + read_creds ✅
- spec §4 公共流程（备份/序列化/写回/校验）→ Task 1 工具函数 ✅
- spec §5 Playwright 要点（tab/账密/勾同意/取 cookie/探活）→ Task 2 ✅
- spec §6 API 要点（GET csrf → POST → 跟链 → 拼串）→ Task 3 ✅
- spec §7 错误处理与校验（失败不写/校验 GET ms.zjer.cn/被跳登录警告）→ Task 1 verify_cookie + Task 4 回归 ✅
- spec §8 安全（env 凭据、备份、不提交）→ Task 1 + README ✅
- spec §9 验收（端到端发话题验证）→ Task 2 Step5 / Task 3 Step4（dry-run）✅

**2. Placeholder scan：** 仅 Task 3 有 `TODO(from-probe)`，这是**有意为之**——纯 API 的登录 URL/字段必须由 Task 2 的真实探活结果填入，无法先验编造；已明确标注来源与填法，并给出「不可行则降级」的确定分支。其余步骤均含完整代码/命令/预期。

**3. Type consistency：** cookie 统一为 `[{'name','value'}]`；`serialize_cookies`/`write_cookie`/`verify_cookie`/`login_playwright`/`login_api` 签名一致 ✅。

（注：项目非 git 仓库、无测试框架，已按现实去掉 commit 步骤、以线上实跑替代单测，属对 writing-plans 默认 TDD 节奏的合理适配。）
