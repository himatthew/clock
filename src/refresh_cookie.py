#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
之江汇 Cookie 自动刷新
登录 szkj/ms.zjer.cn 工作室 SSO -> 取全量 Cookie(含发布必需的 ck_ms) -> 覆盖 cookies.txt(先备份)。
供现有 4 个发布脚本复用。凭据走环境变量 ZJER_USER / ZJER_PASS。

用法:
  ZJER_USER=hzyh2508192 ZJER_PASS='Hy53465927!' python3 refresh_cookie.py
  ZJER_USER=... ZJER_PASS=... python3 refresh_cookie.py --mode api
  python3 refresh_cookie.py --no-headless   # 弹窗调试
"""
import os, sys, time, argparse, requests
from urllib.parse import urlencode, quote

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
# 云管理台(cube)登录入口: 经 yun.zjer.cn/manage 下发 eduyun_sessionid 管理会话,
# state 回跳 ms.zjer.cn 工作室首页。发资源/话题需此管理会话(用户实测唯一可用入口)。
WEB_AUTH_URL = ("https://szkj.zjer.cn/hlwxx/webAuthorize?appId=116397&redirect_url="
                + quote("https://yun.zjer.cn/manage/account/frontend/link/cube/login"
                        "?state=aHR0cHM6Ly9tcy56amVyLmNuL2luZGV4LnBocD9yPXN0dWRpby9pbmRleCZzaWQ9MjE3NA==",
                        safe=''))
# 校验用: 名师工作室话题发布页(受登录保护)
VERIFY_URL = "https://ms.zjer.cn/index.php?r=studio/topic/add&sid=2174"
# 资源上传页(用户实测的真正链接: 原样, name=JSON转义字面量, url 双层编码)
STUDIO_UPLOAD_URL = r"https://ms.zjer.cn/index.php?r=studio/resources/upload&sid=2174&name=%22%5Cu8d44%5Cu6e90%5Cu5217%5Cu8868%22&url=%252Findex.php%253Fr%253Dstudio%252Fresources%2526sid%253D2174"
# 文章发布页: 需 eduyun_sessionid 管理会话(短命), 仅 ck_ms 不足以发布 -> --check --strict 用
ARTICLE_ADD_URL = "https://ms.zjer.cn/index.php?r=studio/post/add&sid=2174"
DEFAULT_COOKIE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cookies.txt")
# 发布必需的会话标记: ck_ms(名师工作室 session) 或 eduyun_sessionid(云管理台管理会话)。
# 注意: WEB_MicroDigitalAccessToken 仅是互联网学校(szyx)态, 不能用于 ms.zjer.cn 发布, 不算。
AUTH_MARKERS = ("ck_ms", "eduyun_sessionid")


def has_auth_session(cookie_str):
    return any(m in cookie_str for m in AUTH_MARKERS)


def log(*a):
    print(*a, flush=True)


def read_creds():
    u = os.environ.get("ZJER_USER")
    p = os.environ.get("ZJER_PASS")
    if not u or not p:
        raise SystemExit("缺少凭据: 请设置环境变量 ZJER_USER 和 ZJER_PASS (或写工作区 .env)")
    return u, p


def load_env_file(path=None):
    """若存在 .env 则载入为环境变量(不覆盖已存在的真实 env)。便于本地免传参运行。"""
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    log(f"已从 .env 载入凭据环境变量")


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
    # ck_ms 是名师工作室发布态的决定性本地标记(ms.zjer.cn 话题页是 SPA, 静态 HTML 无法判定登录态)
    if "ck_ms" in cookie_str:
        log("✅ 校验: Cookie 含 ck_ms(工作室发布态), 可用于 ms.zjer.cn 发布")
        return True
    h = {"Cookie": cookie_str, "User-Agent": UA}
    try:
        r = requests.get(VERIFY_URL, headers=h, timeout=30, allow_redirects=False)
    except Exception as e:
        log(f"校验请求异常: {e}")
        return False
    loc = r.headers.get("Location", "")
    # 被跳登录 = 失败迹象
    if r.status_code in (301, 302, 303, 307) and ("login" in loc.lower() or "passport" in loc.lower()):
        log(f"⚠️ 校验: 被重定向到登录页 ({loc[:80]}), 缺少 ck_ms, SSO 未覆盖工作室")
        return False
    log(f"⚠️ 校验: 无 ck_ms 且状态码={r.status_code}, 未明确判定")
    return False


def check_cookie_valid(cookie_path, strict=False):
    """检测 cookies.txt 是否仍有效(可用于发布)。返回 True/False。
    失效才刷新: 对比盲目每次刷新, 仅当此函数返回 False 时才真正调登录刷新。
    strict=True 时额外检测文章发布页(add)权限 —— 该页需 eduyun_sessionid 管理会话
    (短命, 仅持 ck_ms 会被判无权限), 普通话题/资源页只需 ck_ms。
    实现: 直接 HTTP 请求受保护页, 判断是否被跳登录页或返回'无权限'。
    本机 aTrust 代理会卡死握手, 故强制 proxies=None 绕过。
    """
    if not os.path.exists(cookie_path) or os.path.getsize(cookie_path) == 0:
        log("⚠️ check: cookies.txt 缺失或为空, 判定失效")
        return False
    cookie_str = open(cookie_path, encoding="utf-8").read().strip()
    if not has_auth_session(cookie_str):
        log("⚠️ check: 不含 ck_ms/eduyun_sessionid, 判定失效")
        return False
    h = {"Cookie": cookie_str, "User-Agent": UA}
    no_proxy = {"http": None, "https": None}
    # 基础: 工作室话题发布页, 被跳登录=失效
    try:
        r = requests.get(VERIFY_URL, headers=h, timeout=30,
                         allow_redirects=False, proxies=no_proxy)
    except Exception as e:
        log(f"⚠️ check: 话题页请求异常({e}), 判定失效")
        return False
    loc = r.headers.get("Location", "")
    if r.status_code in (301, 302, 303, 307) and ("login" in loc.lower() or "passport" in loc.lower()):
        log("⚠️ check: 话题页跳登录, 判定失效")
        return False
    if strict:
        try:
            r2 = requests.get(ARTICLE_ADD_URL, headers=h, timeout=30,
                              allow_redirects=False, proxies=no_proxy)
        except Exception as e:
            log(f"⚠️ check(strict): 文章页请求异常({e}), 判定失效")
            return False
        loc2 = r2.headers.get("Location", "")
        if r2.status_code in (301, 302, 303, 307) and ("login" in loc2.lower() or "passport" in loc2.lower()):
            log("⚠️ check(strict): 文章页跳登录, 判定失效")
            return False
        body = r2.text or ""
        if "无权限" in body:
            log("⚠️ check(strict): 文章页返回'无权限', 判定失效")
            return False
    log("✅ check: Cookie 有效" + (" (含文章发布权限)" if strict else ""))
    return True


def login_playwright(user, pwd, headless=True):
    from playwright.sync_api import sync_playwright
    login_posts = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
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

        # 4) 点登录 (Element UI 主按钮)
        try:
            page.locator('button.el-button--primary').first.click(timeout=8000)
            log("已点『登录』(button.el-button--primary)")
        except Exception:
            try:
                page.get_by_text("登录", exact=True).first.click(timeout=8000)
                log("已点『登录』(text)")
            except Exception as e:
                log(f"点『登录』失败: {e}")
        log("已点『登录』, 等待重定向...")

        # 等待 SSO 跳转完成(登录成功后经 yun.zjer.cn 云管理台, 最终回跳 ms.zjer.cn 工作室)
        sso_ok = False
        try:
            page.wait_for_url("**/ms.zjer.cn/**", timeout=30000)
            log("已跳转到 ms.zjer.cn (工作室 SSO 完成)")
            sso_ok = True
        except Exception as e:
            log(f"等待 ms.zjer.cn 跳转超时, 检查是否落在云管理台: {e}")
            try:
                page.wait_for_url("**/yun.zjer.cn/**", timeout=12000)
                log("已落在 yun.zjer.cn 云管理台(管理会话已建立), 继续收 cookie")
                sso_ok = True
            except Exception as e2:
                log(f"也未落在云管理台(登录可能失败): {e2}")
        page.wait_for_timeout(3000)
        # 明确访问工作室发布页/资源上传页, 确保 ck_ms + eduyun_sessionid 等会话 cookie 下发
        # (资源上传页需浏览器执行 JS 才会下发 eduyun_sessionid, ossGetAuthorization 必需)
        if sso_ok:
            for url in (VERIFY_URL, STUDIO_UPLOAD_URL):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3500)
                    log(f"已访问 {url} (触发会话 cookie)")
                except Exception as e:
                    log(f"访问 {url} 异常(可忽略): {e}")

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
        if not sso_ok:
            log("⚠️ 未跳转到 szyx.zjer.cn, 登录可能失败, 返回空(不写盘)")
            return []
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
    # Element UI 复选框: 真实 input 为 .el-checkbox__original(被隐藏),
    # 需点击其外层 label.el-checkbox / .el-checkbox__input 才能切换 v-model 状态。
    try:
        cb = page.locator('label.el-checkbox').first
        if cb.count():
            cb.click(timeout=4000)
            checked = page.evaluate(
                "() => { const c=document.querySelector('input.el-checkbox__original');"
                " return c ? c.checked : false; }")
            if checked:
                return "label.el-checkbox"
    except Exception:
        pass
    # 兜底: 点可见的勾选框
    try:
        box = page.locator('.el-checkbox__input').first
        if box.count():
            box.click(timeout=4000)
            return "el-checkbox__input"
    except Exception:
        pass
    # JS 兜底强制 checked (仅靠原生 checked 不一定触发 Vue, 但可作为最后手段)
    try:
        page.evaluate("""() => { const c=document.querySelector('input.el-checkbox__original');
            if(c){ c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true})); } }""")
        return "js.checked"
    except Exception as e:
        return f"fail:{e}"


def login_api(user, pwd):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Content-Type": "application/json",
                      "Accept": "application/json"})
    # 1) GET 授权页, 收初始 cookie
    r0 = s.get(WEB_AUTH_URL, timeout=30)
    log(f"api: 授权页 status={r0.status_code}")

    # 1.5) initLoginPage: 部分站点需要先用 appId 换 token
    try:
        ri = s.post("https://uc.zjedu.com/api/uc/initLoginPage",
                    json={"appId": 116397}, timeout=30)
        log(f"api: initLoginPage status={ri.status_code}")
    except Exception as e:
        log(f"api: initLoginPage err: {e}")

    # 2) JSON POST 登录 (端点/字段由 Playwright 探活得到, appId 为统一门户值)
    LOGIN_API_URL = "https://uc.zjedu.com/api/uc/login"
    payload = {"mobile": user, "passwd": pwd, "appId": 116397, "roleType": 1}
    r1 = s.post(LOGIN_API_URL, json=payload, timeout=30)
    log(f"api: 登录 POST status={r1.status_code}")
    try:
        j = r1.json()
        code = j.get("code")
        msg = str(j.get("msg", ""))
        log(f"api: 登录响应 code={code} msg={msg} body={str(j)[:160]}")
        # 失败/锁定/错误判据: 任何非成功或含错误关键字都视为未登录
        if code not in (0, 200, "0", "200") or any(k in msg for k in ("失败", "锁定", "错误", "超过")):
            log(f"api: 登录未成功(code={code} msg={msg}), 保留旧 cookie")
            return []
        # 登录成功可能返回 redirectUrl, 需回跳完成 SSO
        data = j.get("data") or {}
        redir = data.get("redirectUrl") or data.get("url") or data.get("redirect")
        if redir:
            log(f"api: 跟随登录返回 redirectUrl 完成 SSO")
            try:
                s.get(redir, timeout=30, allow_redirects=True)
            except Exception as e:
                log(f"api: 跟随 redirectUrl 异常(可忽略): {e}")
    except Exception as e:
        log(f"api: 响应非 JSON({e}), body前120={r1.text[:120]}")
        return []

    # 3) 触发 SSO 链: 带 uc 的 session 回访问授权页(落到工作室) + 受保护页
    #    资源上传页会下发 eduyun_sessionid(ossGetAuthorization 必需), 必须访问
    try:
        s.get(WEB_AUTH_URL, timeout=30, allow_redirects=True)
        s.get(VERIFY_URL, timeout=30, allow_redirects=True)
        s.get(STUDIO_UPLOAD_URL, timeout=30, allow_redirects=True)
    except Exception as e:
        log(f"api: 补跟 SSO 异常(可忽略): {e}")

    cookies = [{"name": c.name, "value": c.value} for c in s.cookies]
    ck_ms = any(c["name"] == "ck_ms" for c in cookies)
    log(f"api: 收到 {len(cookies)} 条 cookie, ck_ms={'有' if ck_ms else '无'}")
    return cookies


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cookie", nargs="?", default=DEFAULT_COOKIE_PATH, help="cookies.txt 路径(默认脚本同目录)")
    ap.add_argument("--mode", choices=["playwright", "api"], default="playwright")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", dest="headless", action="store_false", help="弹窗可视化调试")
    ap.add_argument("--check", action="store_true", help="仅检测 cookie 是否有效(不刷新), 退出码 0=有效 1=失效")
    ap.add_argument("--strict", action="store_true", help="--check 时额外检测文章发布页(add)权限(需 eduyun_sessionid)")
    args = ap.parse_args()

    # 失效检测模式: 不刷新, 只返回有效性(不需要凭据)
    if args.check:
        valid = check_cookie_valid(args.cookie, strict=args.strict)
        sys.exit(0 if valid else 1)

    load_env_file()  # 若工作区有 .env 则自动读取(不覆盖真实 env)
    user, pwd = read_creds()
    log(f"mode={args.mode} headless={args.headless} user={user}")

    if args.mode == "playwright":
        cookies = login_playwright(user, pwd, headless=args.headless)
    else:
        cookies = login_api(user, pwd)

    if not cookies:
        raise SystemExit("❌ 登录未取到 Cookie, 保留旧 cookies.txt, 退出")

    cookie_str = serialize_cookies(cookies)
    # 双重防护: 串不能过短, 且必须含有效登录态标记, 否则视为登录失败, 不覆盖旧 Cookie
    if len(cookie_str) < 30 or not has_auth_session(cookie_str):
        raise SystemExit("❌ 取到的 Cookie 不含有效登录态(无 ck_ms/eduyun_sessionid 等), "
                         "疑似登录失败, 保留旧 cookies.txt")

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
