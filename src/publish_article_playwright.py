#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""之江汇名师工作室(ms.zjer.cn) —— 发布当日文章到「教师文章」栏目

读取 docs/articles/<今天日期>_*.md, 解析标题/正文, 填表提交。
表单字段(post_frm):
  * 标题      : input[name=title]  (maxlength=30, 超长截断)
  * 分类      : ztree 节点 教师文章 -> 点 #treeDemo2_2_a (onclick=move('60423')) 写 parentId=60423
  * 内容      : UEditor 实例 (UE.instants[0]) setContent(HTML)
  * 属性      : input#iso value=0 本人原创  -> 点 label[for=iso]
  * 作者      : input[name=author] = 洪彦
  * 缩略图    : 不传
提交按钮: input.tea_btnColor.wbluebtn (value=发布)

当天可能有多篇文章(默认每天 2 篇, 文件名 <date>_*.md / <date>_2_*.md),
本脚本会循环发布当天所有匹配文章。

日志只输出「标题 + 正文 + 成功/失败」, 调试细节落盘到 article_debug.* 不刷屏。

Cookie 由刷新任务维护(本脚本只读 cookies.txt)。
用法:
  python3 publish_article_playwright.py cookies.txt
  python3 publish_article_playwright.py cookies.txt --date 2026-07-19   # 指定日期
  python3 publish_article_playwright.py cookies.txt --file docs/articles/2026-07-19_xxx.md
  python3 publish_article_playwright.py cookies.txt --dry-run          # 只解析不提交
  python3 publish_article_playwright.py cookies.txt --mode whitebox    # 白盒: 开浏览器填好不提交, 供排查
"""
import os, re, sys, argparse, glob, datetime
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(HERE, "..", "cookies.txt")
ARTICLES_DIR = os.path.join(HERE, "..", "data", "articles")
DEBUG_DIR = os.path.join(HERE, "..", "data", "_debug")
os.makedirs(DEBUG_DIR, exist_ok=True)
POST_URL = "https://ms.zjer.cn/index.php?r=studio/post/add&sid=2174&catid=54161"
# 提交目标: 与表单 action 一致(带 catid 以匹配页面上下文)
POST_SUBMIT_URL = POST_URL
AUTHOR = "洪彦"
CATEGORY_NODE = "#treeDemo2_2_a"          # 教师文章 (move('60423') -> parentId=60423)
CATEGORY_VALUE = "60423"
ORIGINAL_LABEL = 'label[for="iso"]'      # 本人原创
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def log(*a):
    print(*a, flush=True)


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def parse_cookies(s):
    c = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        name, value = part.split("=", 1) if "=" in part else (part, "")
        if name.strip() in ("ACCOUNT", "PASSWORD"):
            continue
        c.append({"name": name.strip(), "value": value.strip(),
                  "domain": ".zjer.cn", "path": "/"})
    return c


def find_article(date, explicit=None):
    """返回匹配 date 的文章文件路径列表(当天可能多篇, 如两篇/日)。"""
    if explicit:
        if not os.path.exists(explicit):
            raise SystemExit(f"指定文章不存在: {explicit}")
        return [explicit]
    prefix = os.path.join(ARTICLES_DIR, date + "_")
    fs = sorted(glob.glob(prefix + "*.md"))
    if not fs:
        raise SystemExit(f"docs/articles 下没有匹配 {date} 的文章 (期望 {prefix}*.md)")
    return fs


def parse_article(path):
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    title = None
    for ln in lines:
        m = re.match(r"^#\s+(.*)$", ln)
        if m:
            title = m.group(1).strip()
            break
    if not title:
        base = os.path.splitext(os.path.basename(path))[0]
        title = base.split("_", 1)[1] if "_" in base else base
    # 正文: 去掉 # 标题行 与 > 主题/元信息行, 其余作为正文
    body = []
    for ln in lines:
        if re.match(r"^#\s+", ln):
            continue
        if re.match(r"^>\s*主题", ln) or re.match(r"^>\s*日期", ln):
            continue
        body.append(ln)
    return title, "\n".join(body).strip(), os.path.basename(path)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_html(md):
    """极简 markdown -> HTML: 段落 <p>, 三级/二级标题, -/* 列表, 段内换行 <br>。"""
    blocks = re.split(r"\n\s*\n", md.strip())
    out = []
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    for blk in blocks:
        blk = blk.strip()
        if not blk:
            continue
        if re.match(r"^[-*]\s+", blk, re.M):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            for li in blk.splitlines():
                li = re.sub(r"^[-*]\s+", "", li).strip()
                if li:
                    out.append(f"<li>{esc(li)}</li>")
            continue
        close_ul()
        if blk.startswith("### "):
            out.append(f"<h3 style=\"font-size:16px;margin:14px 0 6px;\">{esc(blk[4:].strip())}</h3>")
        elif blk.startswith("## "):
            out.append(f"<h2 style=\"font-size:18px;margin:16px 0 6px;\">{esc(blk[3:].strip())}</h2>")
        else:
            para = esc(blk).replace("\n", "<br>")
            out.append(f"<p style=\"margin:8px 0;line-height:1.8;\">{para}</p>")
    close_ul()
    return "\n".join(out)


def set_ueditor_content(page, html):
    ed = page.evaluate("""() => {
        const start = Date.now();
        while (Date.now() - start < 25000) {
            if (window.UE && window.UE.instants) {
                const keys = Object.keys(UE.instants);
                if (keys.length) {
                    const k = keys[0];
                    return {key: k, has: !!UE.instants[k].setContent};
                }
            }
            const e = new Date(); while (new Date() - e < 200) {}
        }
        return null;
    }""")
    if ed and ed.get("has"):
        page.evaluate(
            "([t,k]) => { try { UE.instants[k].setContent(t); } catch(e){} }",
            [html, ed["key"]])
    else:
        page.evaluate("(t) => { const ta = document.querySelector('textarea[name=content]'); if (ta) ta.value = t; }", html)


def fill_form(page, title, html):
    """填表 1~6 步: 标题 / 分类 / 内容 / 属性 / 作者 / 承诺。"""
    # 1) 标题
    page.fill('input[name="title"]', title[:30])
    # 2) 分类: 教师文章
    try:
        page.click(CATEGORY_NODE, timeout=5000)   # CATEGORY_NODE = #treeDemo2_2_a
        page.wait_for_timeout(600)
    except Exception:
        pass
    # 兜底: 直接调用 move('60423') + 显式写两个隐藏域 + 给 li 加 curSelectedNode 类
    page.evaluate(f"""() => {{
        try {{ if (typeof move === 'function') move('{CATEGORY_VALUE}'); }} catch(e){{}}
        const pid = document.querySelector('#parentId');
        const tid = document.querySelector('#parent_category');
        if (pid) pid.value = '{CATEGORY_VALUE}';
        if (tid) tid.value = '{CATEGORY_VALUE}';
        const li = document.querySelector('#treeDemo2_2');
        if (li && !li.classList.contains('curSelectedNode')) li.classList.add('curSelectedNode');
    }}""")
    page.wait_for_timeout(800)
    # 3) 内容
    set_ueditor_content(page, html)
    page.wait_for_timeout(1000)
    # 4) 属性: 本人原创
    try:
        page.click(ORIGINAL_LABEL, timeout=5000)
    except Exception:
        page.evaluate("""() => {
            const r = document.querySelector('input#iso');
            if (r) { r.checked = true; const l = document.querySelector('label[for=iso]');
                     if (l) l.classList.add('hRadio_Checked'); }
        }""")
    page.wait_for_timeout(500)
    # 5) 作者
    page.fill('input[name="author"]', AUTHOR)
    page.wait_for_timeout(500)
    # 6) 承诺 checkbox
    try:
        page.click('label:has-text("承诺")', timeout=5000)
    except Exception:
        page.evaluate("""() => {
            const labs = [...document.querySelectorAll('label')];
            const l = labs.find(x => (x.innerText || '').includes('承诺'));
            if (l) { const cb = l.querySelector('input[type=checkbox]'); if (cb) cb.checked = true; }
        }""")
    page.wait_for_timeout(500)


def publish_one(page, path, mode, dialogs, idx, total):
    """发布单篇文章: 重载 add 页 -> 无权限守卫 -> 填表 -> 完整 POST -> 列表验证。"""
    title, body, fname = parse_article(path)
    html = md_to_html(body)

    # —— 日志只显示 标题 + 正文 ——
    log(f"\n📄 第 {idx}/{total} 篇：{title}")
    log("──────────── 正文 ────────────")
    log(body)
    log("────────────────────────────")

    if mode == "whitebox":
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        fill_form(page, title, html)
        try:
            shot = os.path.join(DEBUG_DIR, "article_whitebox.png")
            page.screenshot(path=shot, full_page=True)
        except Exception:
            pass
        log("=== 白盒模式: 表单已填好, 未提交, 见 article_whitebox.png ===")
        return 0

    # 每次重新加载 add 页(上一次提交会跳走到 list, 需回到发布页)
    page.goto(POST_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3500)

    # 无权限守卫
    guard = page.evaluate("() => (document.body ? document.body.innerText : '').includes('无权限')")
    if guard:
        log(f"❌ 发布失败：{title}（页面显示无权限, 会话不足, 本批中止）")
        return 2

    fill_form(page, title, html)

    # 提交: 绕过 post.js 的字段裁剪 —— 直接收集表单全部 named 字段并完整 POST。
    post_payload = page.evaluate("""() => {
        const frm = document.querySelector('#post_frm');
        const fd = new FormData(frm);
        const obj = {};
        for (const [k, v] of fd.entries()) {
            if (obj[k] === undefined) obj[k] = v;
            else if (Array.isArray(obj[k])) obj[k].push(v);
            else obj[k] = [obj[k], v];
        }
        return obj;
    }""")
    post_payload["catid"] = "54161"
    import urllib.parse as _up
    post_body = _up.urlencode(post_payload, doseq=True)
    try:
        resp = page.request.post(
            POST_SUBMIT_URL,
            data=post_body,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                      "Referer": POST_SUBMIT_URL})
        resp_text = resp.text() or ""
    except Exception:
        resp_text = ""
    # 诊断落盘(不刷屏)
    try:
        open(os.path.join(DEBUG_DIR, "article_resp.txt"), "w").write(resp_text)
    except Exception:
        pass

    ok = False
    if any(k in page.url for k in ("post/index", "post/list", "post/manage", "post/show", "post/view")):
        ok = True
    if "成功" in resp_text or "添加成功" in resp_text:
        ok = True
    for m in dialogs:
        if "成功" in m:
            ok = True
        if any(w in m for w in ("失败", "错误", "请选择", "不能为空")):
            ok = False
    if any(w in resp_text for w in ("失败", "错误", "请选择", "不能为空")):
        ok = False

    # 权威验证: 去"教师文章"列表查本篇标题是否出现, 命中即视为发布成功。
    try:
        verify_url = "https://ms.zjer.cn/index.php?r=studio/post/list&sid=2174&cid=60423"
        page.goto(verify_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        for _ in range(5):
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(600)
        lst_txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        hit = title[:10] in lst_txt
        if hit:
            ok = True
    except Exception:
        hit = False

    if ok:
        log(f"✅ 发布成功：{title}")
    else:
        # 失败: 落盘诊断文件供排查
        try:
            full_txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
            open(os.path.join(DEBUG_DIR, "article_debug.html"), "w").write(page.content() or "")
            open(os.path.join(DEBUG_DIR, "article_debug.txt"), "w").write(full_txt)
            pats = [r"请选择\S{0,12}", r"不能为空", r"失败\S{0,10}", r"错误\S{0,10}",
                    r"必填\S{0,8}", r"未选择\S{0,10}"]
            reasons = []
            for pat in pats:
                reasons += re.findall(pat, full_txt)
                reasons += re.findall(pat, resp_text)
            log(f"❌ 发布失败：{title}" + (f"（原因: {', '.join(reasons)}）" if reasons else "（见 article_debug.html）"))
        except Exception:
            log(f"❌ 发布失败：{title}")
    return 0 if ok else 1


def publish(cookie_path, date, explicit, dry_run, mode):
    paths = find_article(date, explicit)
    total = len(paths)

    if dry_run:
        log(f"[预览] 当天共 {total} 篇文章待发布:\n")
        for i, p in enumerate(paths, 1):
            title, body, fname = parse_article(p)
            log(f"📄 第 {i}/{total} 篇：{title}")
            log("──────────── 正文 ────────────")
            log(body)
            log("────────────────────────────\n")
        return 0

    cookie = open(cookie_path, encoding="utf-8").read().strip()
    with sync_playwright() as p:
        headless = (mode == "auto")
        if mode == "whitebox" and not sys.stdin.isatty():
            headless = True
        b = p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(user_agent=UA)
        ctx.add_cookies(parse_cookies(cookie))
        page = ctx.new_page()
        dialogs = []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

        rc = 0
        for i, path in enumerate(paths, 1):
            dialogs.clear()  # 每篇独立判断弹窗, 不清会影响下一篇 ok 判定
            r = publish_one(page, path, mode, dialogs, i, total)
            if r == 2:
                b.close()
                return 2
            if r != 0:
                rc = r
        b.close()
        return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cookie", nargs="?", default=COOKIES_FILE, help="cookies.txt 路径")
    ap.add_argument("--date", default=None, help="指定文章日期 YYYY-MM-DD (默认今天)")
    ap.add_argument("--file", default=None, help="显式指定 md 文件(覆盖日期匹配)")
    ap.add_argument("--mode", choices=["auto", "whitebox"], default="auto",
                    help="auto=headless自动提交; whitebox=开浏览器填好不提交供排查")
    ap.add_argument("--dry-run", action="store_true", help="只解析+预览, 不打开浏览器不提交")
    args = ap.parse_args()

    date = args.date or today_str()
    rc = publish(args.cookie, date, args.file, args.dry_run, args.mode)
    sys.exit(rc)


if __name__ == "__main__":
    main()
