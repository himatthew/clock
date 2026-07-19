#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""之江汇名师工作室(ms.zjer.cn) —— 话题发布 + 置顶/加精 管理
流程:
  1. 读 topics_config.json, 按 date==今天 匹配, fallback default, 取 title/content
  2. Playwright 发布话题, 取新 id
  3. 找出「洪彦」名下【置顶+加精】旧话题, 批量撤顶+取消加精
  4. 新话题置顶+加精
Cookie 由 run_daily.sh 第一步 refresh_cookie.py 维护(本脚本只读 cookies.txt)。
"""
import os, re, sys, json, datetime
from playwright.sync_api import sync_playwright
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = {
    "BASE": "https://ms.zjer.cn",
    "SID": "2174",
    "COOKIES_FILE": os.path.join(HERE, "..", "cookies.txt"),
    "TOPICS_CONFIG": os.path.join(HERE, "..", "config", "topics_config.json"),
    "HONGYAN_NAME": "洪彦",
    "UA": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def load_cookies(path):
    cookies = {}
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k.strip() in ("ACCOUNT", "PASSWORD"):
            continue
        cookies[k.strip()] = v.strip()
    return cookies


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def load_topic_config():
    with open(CONFIG["TOPICS_CONFIG"], encoding="utf-8") as f:
        cfg = json.load(f)
    dk = today_str()
    for it in cfg.get("topics", []):
        if it.get("date") == dk:
            return it["title"], it["content"]
    d = cfg.get("default")
    if d:
        return d["title"], d["content"]
    raise SystemExit(f"配置里无 {dk} 的话题, 也无 default")


def new_session(cookies):
    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update({"User-Agent": CONFIG["UA"], "Accept-Language": "zh-CN,zh;q=0.9"})
    return s


def get_csrf(s):
    url = f"{CONFIG['BASE']}/index.php?r=studio/topic/add&sid={CONFIG['SID']}"
    r = s.get(url, timeout=30)
    m = re.search(r'csrftk=([0-9a-f]+)', r.text)
    return m.group(1) if m else s.cookies.get("YII_CSRF_TOKEN")


def publish_topic_playwright(title, content):
    new_id = None
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(user_agent=CONFIG["UA"])
        raw = open(CONFIG["COOKIES_FILE"], encoding="utf-8").read().strip()
        pw = []
        for part in re.sub(r";\s*(ACCOUNT|PASSWORD)=[^;]*", "", raw).split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            pw.append({"name": k.strip(), "value": v.strip(), "domain": ".zjer.cn", "path": "/"})
        ctx.add_cookies(pw)
        page = ctx.new_page()
        page.goto(f"{CONFIG['BASE']}/index.php?r=studio/topic/add&sid={CONFIG['SID']}",
                  wait_until="domcontentloaded", timeout=30000)
        page.fill("#title", title)
        ed = page.evaluate("""() => {
            const start = Date.now();
            while (Date.now() - start < 25000) {
                if (window.UE && window.UE.instants) {
                    const keys = Object.keys(UE.instants);
                    if (keys.length) {
                        const k = keys[0]; const inst = UE.instants[k];
                        return {key: k, hasSetContent: !!inst.setContent};
                    }
                }
                const e = new Date(); while (new Date() - e < 200) {}
            }
            return null;
        }""")
        if ed and ed.get("hasSetContent"):
            page.evaluate("([t,k]) => { try { UE.instants[k].setContent(t); return 'ok'; } catch(e){ return 'err:'+e; } }",
                          [content, ed["key"]])
        else:
            page.evaluate("(t) => { const ta = document.querySelector('textarea[name=content]'); if (ta) ta.value = t; }", content)
        page.wait_for_timeout(1500)
        page.click("#topic_butt")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        m = re.search(r'[?&]id=(\d+)', page.url)
        if m:
            new_id = m.group(1)
        b.close()
    return new_id


def get_topped_ids(s):
    topped = set()
    for page in range(1, 6):
        url = f"{CONFIG['BASE']}/index.php?r=studio/topic/index&sid={CONFIG['SID']}"
        if page > 1:
            url += f"&page={page}"
        r = s.get(url, timeout=30)
        for m in re.finditer(r"<i class='top'>置顶</i><i class='special'>精</i>\s*<a[^>]*?(?:&|\?)id=(\d+)", r.text):
            topped.add(m.group(1))
        if "class='top'" not in r.text:
            break
    return topped


def get_authors(s):
    authors = {}
    for page in range(1, 20):
        url = f"{CONFIG['BASE']}/index.php?r=studio/manage/topic/list&sid={CONFIG['SID']}&page={page}"
        r = s.get(url, timeout=30)
        rows = re.findall(r"<tr>(.*?)</tr>", r.text, re.S)
        if not rows:
            break
        for tr in rows:
            m = re.search(r'name="ck1\[\]"[^>]*value="(\d+)"', tr)
            if not m:
                continue
            tid = m.group(1)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            authors[tid] = re.sub(r"<.*?>", "", tds[2]).strip() if len(tds) > 2 else "?"
    return authors


def manage_action(s, csrf, ids, action):
    if not ids:
        return "(无)"
    url = f"{CONFIG['BASE']}/index.php?r=studio/manage/topic/manage&sid={CONFIG['SID']}&tid={CONFIG['SID']}"
    s.headers["X-Requested-With"] = "XMLHttpRequest"
    s.headers["Referer"] = f"{CONFIG['BASE']}/index.php?r=studio/manage/topic/list&sid={CONFIG['SID']}"
    data = {"YII_CSRF_TOKEN": csrf, "ck1": ",".join(ids), "action": action}
    r = s.post(url, data=data, timeout=30)
    return r.text.strip()


def main():
    title, content = load_topic_config()
    print(f"[话题] {today_str()}: {title}")
    cookies = load_cookies(CONFIG["COOKIES_FILE"])
    s = new_session(cookies)
    csrf = get_csrf(s)
    if not csrf:
        print("[CSRF] ❌ 未获取到, 中止")
        sys.exit(1)
    new_id = publish_topic_playwright(title, content)
    if not new_id:
        print("[话题] ⚠️ URL 未取到 id, 用标题回查")
        r = s.get(f"{CONFIG['BASE']}/index.php?r=studio/topic/index&sid={CONFIG['SID']}", timeout=30)
        m = re.search(r'(?:&|\?)id=(\d+)[^>]*>' + re.escape(title), r.text)
        new_id = m.group(1) if m else None
    if not new_id:
        print("[话题] ❌ 无法定位新话题, 跳过置顶管理")
        sys.exit(1)
    print(f"[话题] ✅ 新话题 id={new_id}")
    topped = get_topped_ids(s)
    authors = get_authors(s)
    hongyan_topped = [t for t in topped if authors.get(t) == CONFIG["HONGYAN_NAME"]]
    print(f"[话题] 置顶+加精共 {len(topped)}, 洪彦的: {hongyan_topped}")
    old = [t for t in hongyan_topped if t != new_id]
    if old:
        print(f"[话题] 撤顶+取消加精 旧: {old}")
        print("  撤顶:", manage_action(s, csrf, old, "untop"))
        print("  取消加精:", manage_action(s, csrf, old, "unessence"))
    else:
        print("[话题] 洪彦无旧置顶话题, 跳过")
    print(f"[话题] 置顶+加精 新 {new_id}")
    print("  置顶:", manage_action(s, csrf, [new_id], "top"))
    print("  加精:", manage_action(s, csrf, [new_id], "essence"))
    print("[话题] ✅ 完成")


if __name__ == "__main__":
    main()
