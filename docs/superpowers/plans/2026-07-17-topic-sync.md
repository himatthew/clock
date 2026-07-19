# 之江汇自动发布：话题发布+置顶加精+教研留言 同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把分支 `clock/clock` 的三项能力（发布话题、旧话题撤顶取消加精+新话题置顶加精、参与最新一个未加入教研活动并留 5 条言）移植进当前分支，接入现有 06:00 定时任务，微信推送汇总四态。

**Architecture:** 复用当前已验证的 `refresh_cookie.py` + `cookies.txt`（cube 登录态），新增 `publish_topic_manager.py`（Playwright 发布 + requests 管理 API 做置顶/加精）、改造 `join_activity_and_comment.py`（playwright 参与 + 留言）；`run_daily.sh` 顺序追加两步；`notify.py` 扩展两个状态参数。所有路径相对化，本地与服务器通用。

**Tech Stack:** Python 3 + requests + playwright（venv chromium headless）；之江汇 `ms.zjer.cn` 工作室接口；PushPlus 微信推送。

> **版本管理说明：** 当前 `clock` 目录**不是 git 仓库**。如需版本控制，先 `git init`（`.gitignore` 已排除 `cookies.txt`/`cron.log`/`__pycache__`），否则各任务末尾的 commit 步骤跳过即可。

---

## File Structure

| 动作 | 文件 | 职责 |
|---|---|---|
| 新建 | `publish_topic_manager.py` | 发布当天话题 + 旧话题撤顶/取消加精 + 新话题置顶/加精 |
| 复制+改 | `join_activity_and_comment.py` | 参与最新一个未加入教研活动 + 提问研讨栏留 5 条言 |
| 复制 | `提问研讨留言库.docx` | 留言内容源（同目录） |
| 覆盖 | `topics_config.json` | 话题内容源（含 date 排期 + default），分支版 |
| 改 | `run_daily.sh` | 顺序加话题、教研两步，四态传入 notify |
| 改 | `notify.py` | 增加 `--topic-status` / `--activity-status`，正文追加两行 |

保留不动：`refresh_cookie.py`、`publish_resource_*.py`、`resource_config.py`、`topic_config.py`、`publish_topic_api.py`、`publish_topic_playwright.py`。

---

### Task 1: 复制并改造 `join_activity_and_comment.py`

**Files:**
- Create: `join_activity_and_comment.py`

- [ ] **Step 1: 写入完整改造版脚本**

相对化路径、去分支 `refresh_cookies` 依赖、Chrome 走 venv chromium。完整内容：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""之江汇名师工作室(ms.zjer.cn, sid=2174) —— 教研活动自动参与 + 提问研讨留言
流程:
  1) 进教研活动列表, 切「未开始」
  2) 取最新的一个「未开始且未加入且无需邀请码」的活动
  3) 点「立即参与」
  4) 从 提问研讨留言库.docx 随机取 5 条不同留言, 逐条发布
留言来源: 提问研讨留言库.docx (同目录, 标准库 zipfile 解析, 无需 python-docx)
Cookie 由 run_daily.sh 第一步 refresh_cookie.py 维护(本脚本只读 cookies.txt)。
依赖: playwright(venv chromium headless)
用法:
  python3 join_activity_and_comment.py            # 参与最新未开始活动并留5条言
  python3 join_activity_and_comment.py --count 3  # 留3条
  python3 join_activity_and_comment.py --dry-run  # 只预览不操作
  python3 join_activity_and_comment.py --aid 72173
"""
import os, re, sys, json, random, argparse, zipfile
from xml.etree import ElementTree as ET
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = {
    "BASE": "https://ms.zjer.cn",
    "SID": "2174",
    "COOKIES_FILE": os.path.join(HERE, "cookies.txt"),
    "DOCX": os.path.join(HERE, "提问研讨留言库.docx"),
    "HONGYAN_NAME": "洪彦",
    "UA": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "COMMENT_MAX": 140,
}
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def load_messages(docx_path):
    z = zipfile.ZipFile(docx_path)
    xml = z.read("word/document.xml").decode("utf-8")
    root = ET.fromstring(xml)
    msgs = []
    for p in root.iter(W_NS + "p"):
        texts = [t.text for t in p.iter(W_NS + "t") if t.text]
        line = "".join(texts).strip()
        if line:
            msgs.append(line)
    return msgs


def to_pw_cookies(raw):
    out = []
    for part in re.sub(r";\s*(ACCOUNT|PASSWORD)=[^;]*", "", raw).split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out.append({"name": k.strip(), "value": v.strip(), "domain": ".zjer.cn", "path": "/"})
    return out


def find_unstarted_activities(page):
    page.goto(f"{CONFIG['BASE']}/index.php?r=studio/activies/list&sid={CONFIG['SID']}",
              wait_until="networkidle", timeout=60000)
    try:
        page.click("a:has-text('未开始')", timeout=8000)
        page.wait_for_timeout(4000)
    except Exception:
        pass
    cards = page.eval_on_selector_all(
        "a[href*='activiesdetail']",
        """els => els.map(e => {
            const href = e.getAttribute('href') || '';
            const m = href.match(/aid=(\\d+)/);
            const card = e.closest('li') || e.parentElement || e;
            const txt = (card.innerText || e.innerText || '').replace(/\\s+/g, ' ');
            return { aid: m ? m[1] : null,
                     title: (e.getAttribute('title')||(e.innerText||'').trim().split('\\n')[0]||'').slice(0,60),
                     cardText: txt };
        })""")
    seen, ordered = set(), []
    for c in cards:
        if not c["aid"] or c["aid"] in seen:
            continue
        seen.add(c["aid"])
        if "未开始" in c["cardText"]:
            ordered.append({"aid": c["aid"], "title": c["title"]})
    return ordered


def join_status(page, aid):
    page.goto(f"{CONFIG['BASE']}/index.php?r=studio/activies/activiesdetail&sid={CONFIG['SID']}&aid={aid}",
              wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    join_btn = page.query_selector("a[onclick*='joinact']")
    if not join_btn:
        return False, False
    st = join_btn.get_attribute("status")
    return True, (st == "2")


def join_activity(page, aid):
    join_btn = page.query_selector("a[onclick*='joinact']")
    if not join_btn:
        return False
    st = join_btn.get_attribute("status")
    if st == "2":
        return False
    join_btn.click()
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    return True


def post_comment(page, msg):
    box = None
    for sel in ["textarea[placeholder*='还能输入']", "input[placeholder*='还能输入']",
                "textarea", "input[type='text']"]:
        try:
            box = page.wait_for_selector(sel, timeout=6000)
            if box:
                break
        except Exception:
            continue
    if not box:
        return False
    box.fill(msg)
    page.wait_for_timeout(500)
    btn = page.query_selector("[onclick*='commentPublish']")
    if not btn:
        btn = page.query_selector("button:has-text('提交'), a:has-text('提交')")
    if not btn:
        return False
    btn.click()
    page.wait_for_timeout(2500)
    return True


def run(count=5, dry_run=False, aid=None):
    print(f"[教研参与] 留言库={CONFIG['DOCX']} 数量={count} dry_run={dry_run}")
    messages = load_messages(CONFIG["DOCX"])
    if len(messages) < count:
        print(f"[留言] ⚠️ 留言库仅 {len(messages)} 条, 不足 {count}, 将全部使用")
        count = min(count, len(messages))
    print(f"[留言] 留言库共 {len(messages)} 条, 将随机取 {count} 条不同")
    raw = open(CONFIG["COOKIES_FILE"], encoding="utf-8").read().strip()
    pw_cookies = to_pw_cookies(raw)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=CONFIG["UA"])
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()
        if aid:
            target_aid, target_title = aid, "(指定)"
        else:
            ordered = find_unstarted_activities(page)
            print(f"[教研参与] 未开始候选 {len(ordered)}: {[(c['aid'], c['title']) for c in ordered]}")
            target_aid, target_title = None, None
            for c in ordered:
                has_btn, need_code = join_status(page, c["aid"])
                if need_code:
                    print(f"  活动 {c['aid']} 需邀请码, 跳过")
                    continue
                if not has_btn:
                    print(f"  活动 {c['aid']} 已参与, 跳过")
                    continue
                target_aid, target_title = c["aid"], c["title"]
                break
            if not target_aid:
                print("[教研参与] 未找到未开始且未加入的活动, 结束")
                browser.close()
                return
        print(f"[教研参与] 目标活动 aid={target_aid} 《{target_title}》")
        if dry_run:
            chosen = random.sample(messages, count)
            print("[dry-run] 将发布:")
            for i, m in enumerate(chosen, 1):
                print(f"   {i}. {m}")
            browser.close()
            return
        if not aid:
            page.goto(f"{CONFIG['BASE']}/index.php?r=studio/activies/activiesdetail&sid={CONFIG['SID']}&aid={target_aid}",
                      wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
        has_btn, need_code = join_status(page, target_aid)
        if need_code:
            print("[参与] ⚠️ 需邀请码, 跳过参与(仍尝试留言)")
        elif has_btn:
            print("[参与] 点击立即参与...")
            ok = join_activity(page, target_aid)
            print(f"[参与] {'✅ 已参与' if ok else '⚠️ 未确认(可能已参与)'}")
        else:
            print("[参与] 洪彦已在该活动")
        chosen = random.sample(messages, count)
        print(f"[留言] 随机 {len(chosen)} 条:")
        ok_count = 0
        for m in chosen:
            if post_comment(page, m):
                ok_count += 1
                print(f"   ✅ {m[:30]}...")
            else:
                print(f"   ❌ {m[:30]}...")
        print(f"[完成] aid={target_aid} 参与+留言结束, 成功 {ok_count}/{len(chosen)}")
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5, help="留言条数(默认5)")
    ap.add_argument("--dry-run", action="store_true", help="只预览不操作")
    ap.add_argument("--aid", default=None, help="指定活动 aid")
    args = ap.parse_args()
    run(count=args.count, dry_run=args.dry_run, aid=args.aid)
```

- [ ] **Step 2: 语法检查**

Run: `/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -m py_compile join_activity_and_comment.py && echo COMPILE_OK`
Expected: 输出 `COMPILE_OK`（无 traceback）

- [ ] **Step 3: Commit（仅当已 git init）**

```bash
git add join_activity_and_comment.py
git commit -m "feat: 移植教研参与+留言脚本(playwright, 相对路径)"
```

---

### Task 2: 新建 `publish_topic_manager.py`

**Files:**
- Create: `publish_topic_manager.py`

- [ ] **Step 1: 写入完整脚本**

发布当天话题（Playwright）+ 置顶/加精管理（requests API）。完整内容：

```python
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
    "COOKIES_FILE": os.path.join(HERE, "cookies.txt"),
    "TOPICS_CONFIG": os.path.join(HERE, "topics_config.json"),
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
```

- [ ] **Step 2: 语法检查**

Run: `/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -m py_compile publish_topic_manager.py && echo COMPILE_OK`
Expected: `COMPILE_OK`

- [ ] **Step 3: Commit（仅当已 git init）**

```bash
git add publish_topic_manager.py
git commit -m "feat: 新增话题发布+置顶加精管理脚本"
```

---

### Task 3: 复制 `提问研讨留言库.docx` 与 `topics_config.json`

**Files:**
- Copy: `提问研讨留言库.docx`, `topics_config.json`（来自分支 `clock/clock`）

- [ ] **Step 1: 复制两个文件到当前分支**

Run:
```bash
cp "/Users/matthew/workshop/clock/clock/提问研讨留言库.docx" /Users/matthew/workshop/clock/提问研讨留言库.docx
cp /Users/matthew/workshop/clock/clock/topics_config.json /Users/matthew/workshop/clock/topics_config.json
```

- [ ] **Step 2: 校验文件就位且可解析**

Run:
```bash
ls -l /Users/matthew/workshop/clock/提问研讨留言库.docx /Users/matthew/workshop/clock/topics_config.json
/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -c "import json,zipfile; json.load(open('/Users/matthew/workshop/clock/topics_config.json')); z=zipfile.ZipFile('/Users/matthew/workshop/clock/提问研讨留言库.docx'); print('docx ok, doc.xml bytes=', len(z.read('word/document.xml')))"
```
Expected: 两个文件列出；输出 `docx ok, doc.xml bytes= <正数>`（无 JSON/zip 报错）

- [ ] **Step 3: Commit（仅当已 git init）**

```bash
git add 提问研讨留言库.docx topics_config.json
git commit -m "feat: 引入留言库 docx 与分支版话题排期配置"
```

---

### Task 4: 改造 `run_daily.sh`

**Files:**
- Modify: `run_daily.sh`

- [ ] **Step 1: 用以下完整内容覆盖 `run_daily.sh`**

```bash
#!/usr/bin/env bash
# 之江汇教育广场 每日自动发布 (陈晓雯名师工作室 sid=2174, 账号 洪彦)
# 步骤:
#   1) playwright(cube 云管理台登录)刷新 cookies.txt, 拿到 ck_ms + eduyun_sessionid
#   2) playwright --mode auto 上传 assets/ 下当天日期前缀的 PDF 资源
#   3) 发布当天话题 + 旧话题撤顶取消加精 + 新话题置顶加精
#   4) 参与最新一个未加入教研活动 + 提问研讨留 5 条言
#   5) 微信推送(PushPlus, 四态汇总; 成败都推)
# 由 crontab 每天 06:00 (Asia/Shanghai) 调用: 0 6 * * * /home/ubuntu/clock/run_daily.sh
set -uo pipefail

export TZ=Asia/Shanghai
APP=/home/ubuntu/clock
VENV=/home/ubuntu/venv_clock
PY="$VENV/bin/python"
LOG="$APP/cron.log"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

cd "$APP" || { echo "[$(ts)] ERROR: cd $APP 失败"; exit 1; }

log "=== 每日任务开始 ==="

# 1) 刷新 cookie + sessionId (playwright headless, cube 登录)
log "[1/5] 刷新 cookie (refresh_cookie.py --mode playwright) ..."
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    "$PY" refresh_cookie.py --mode playwright >> "$LOG" 2>&1
CK_EXIT=$?
log "      刷新完成 exit=$CK_EXIT"

# 2) 上传当天资源 (playwright --mode auto: 自动匹配 assets/ 当天前缀)
log "[2/5] 上传当天资源 (publish_resource_playwright.py --mode auto) ..."
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    "$PY" publish_resource_playwright.py cookies.txt --mode auto >> "$LOG" 2>&1
UP_EXIT=$?
log "      上传完成 exit=$UP_EXIT"

# 3) 发布话题 + 旧话题撤顶取消加精 + 新话题置顶加精
log "[3/5] 发布话题+置顶加精 (publish_topic_manager.py) ..."
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    "$PY" publish_topic_manager.py >> "$LOG" 2>&1
TK_EXIT=$?
log "      话题完成 exit=$TK_EXIT"

# 4) 教研参与 + 留言 (playwright: 参与最新一个未加入活动 + 留 5 条言)
log "[4/5] 教研参与+留言 (join_activity_and_comment.py) ..."
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    "$PY" join_activity_and_comment.py >> "$LOG" 2>&1
AC_EXIT=$?
log "      教研完成 exit=$AC_EXIT"

# 5) 微信推送结果 (PushPlus, 读取 .env 的 PUSHPLUS_TOKEN/好友令牌; 四态汇总, 成败都推)
COOKIE_STATUS="成功";   [ "$CK_EXIT" -ne 0 ] && COOKIE_STATUS="失败 (exit=$CK_EXIT)"
UPLOAD_STATUS="成功";   [ "$UP_EXIT" -ne 0 ] && UPLOAD_STATUS="失败 (exit=$UP_EXIT)"
TOPIC_STATUS="成功";    [ "$TK_EXIT" -ne 0 ] && TOPIC_STATUS="失败 (exit=$TK_EXIT)"
ACTIVITY_STATUS="成功"; [ "$AC_EXIT" -ne 0 ] && ACTIVITY_STATUS="失败 (exit=$AC_EXIT)"

# 取当天待发布资源名(去掉日期前缀与扩展名), 用于微信文案
TODAY="$(date '+%Y-%m-%d')"
RESOURCES="$(for f in assets/"$TODAY"_*.pdf; do [ -e "$f" ] || continue; basename "$f" .pdf | sed "s/^${TODAY}_//"; done | paste -sd, -)"

DETAIL="$(tail -n 25 "$LOG")"
log "[5/5] 推送微信通知 (notify.py) ..."
"$PY" notify.py \
    --date "$TODAY" \
    --cookie-status "$COOKIE_STATUS" \
    --upload-status "$UPLOAD_STATUS" \
    --topic-status "$TOPIC_STATUS" \
    --activity-status "$ACTIVITY_STATUS" \
    --resources "$RESOURCES" \
    --detail "$DETAIL" >> "$LOG" 2>&1
log "      推送完成 exit=$?"

log "=== 每日任务结束 ==="
```

- [ ] **Step 2: 语法检查**

Run: `bash -n /Users/matthew/workshop/clock/run_daily.sh && echo BASH_OK`
Expected: `BASH_OK`

- [ ] **Step 3: Commit（仅当已 git init）**

```bash
git add run_daily.sh
git commit -m "feat: run_daily 增加话题发布与教研参与两步, 推送汇总四态"
```

---

### Task 5: 扩展 `notify.py`（增加话题/教研状态）

**Files:**
- Modify: `notify.py`

- [ ] **Step 1: argparse 增加两个参数**

在 `notify.py` 的 `ap.add_argument("--resources", ...)` 行之后插入：

```python
    ap.add_argument("--topic-status", default="未知", help="话题发布状态(成功/失败)")
    ap.add_argument("--activity-status", default="未知", help="教研参与状态(成功/失败)")
```

- [ ] **Step 2: `build_html` 的 rows 增加两行**

在 `build_html` 函数内 `desc_row("资源上传", status_tag(args.upload_status, upload_ok))` 这一行**之后**插入：

```python
        desc_row("话题发布", status_tag(args.topic_status,
                 "成功" in args.topic_status and "失败" not in args.topic_status)),
        desc_row("教研参与", status_tag(args.activity_status,
                 "成功" in args.activity_status and "失败" not in args.activity_status)),
```

（`build_html` 已接收 `args`，直接读取 `args.topic_status` / `args.activity_status` 即可，无需改函数签名。）

- [ ] **Step 3: 语法检查**

Run: `/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -m py_compile notify.py && echo COMPILE_OK`
Expected: `COMPILE_OK`

- [ ] **Step 4: 本地发一条带新参数的测试推送（验证正文追加行）**

Run:
```bash
cd /Users/matthew/workshop/clock && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  /Users/matthew/.workbuddy/binaries/python/envs/default/bin/python notify.py \
  --date "$(date '+%Y-%m-%d')" --cookie-status 成功 --upload-status 成功 \
  --topic-status 成功 --activity-status 成功 --resources "测试资源" \
  --detail "本地验证 notify 四态参数"
```
Expected: 输出 `[主] {"code":200,...}` 与 `[好友1] {"code":200,...}`（微信收到卡片，正文含「话题发布：成功」「教研参与：成功」）

- [ ] **Step 5: Commit（仅当已 git init）**

```bash
git add notify.py
git commit -m "feat: notify 增加话题/教研状态行"
```

---

### Task 6: 本地全量语法校验

**Files:** 无新增，校验已有改动

- [ ] **Step 1: 编译全部改动脚本 + bash 语法**

Run:
```bash
cd /Users/matthew/workshop/clock
/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python -m py_compile publish_topic_manager.py join_activity_and_comment.py notify.py && echo PY_OK
bash -n run_daily.sh && echo BASH_OK
```
Expected: 依次输出 `PY_OK`、`BASH_OK`

---

### Task 7: 同步服务器并端到端验证

**Files:** 同步整个项目（排除运行时文件）到 `124.222.39.165:/home/ubuntu/clock/`

- [ ] **Step 1: rsync 到服务器**

Run:
```bash
rsync -az --exclude 'cookies.txt' --exclude 'cookies.txt.*' --exclude 'cron.log' \
  --exclude '__pycache__' --exclude '.DS_Store' --exclude '.workbuddy' \
  /Users/matthew/workshop/clock/ ubuntu@124.222.39.165:/home/ubuntu/clock/
```
Expected: 列出传输的文件，无报错。

- [ ] **Step 2: 服务器手动跑一次全链路**

Run:
```bash
ssh -o StrictHostKeyChecking=no ubuntu@124.222.39.165 'cd /home/ubuntu/clock && bash run_daily.sh'
```
Expected: 日志依次出现 `[1/5]...[5/5]`，四步均执行；`cron.log` 末尾 notify 返回 `code:200`。

- [ ] **Step 3: 微信核对 + 后台肉眼确认**

- 微信收到「毛毛打卡通知」推送，正文含「话题发布」「教研参与」两行状态。
- 登录之江汇工作室后台确认：新话题已【置顶+加精】、旧洪彦话题已撤顶；目标教研活动已参与且「提问研讨」栏有 5 条新留言。

- [ ] **Step 4: Commit（仅当已 git init，本地）**

```bash
git add -A
git commit -m "feat: 话题发布+置顶加精+教研留言 接入每日定时任务"
```

---

## Self-Review

**1. Spec 覆盖：** 
- §5 文件清单 → Task 1/2/3/4/5 覆盖（新建 publish_topic_manager、改造 join、复制 docx+json、改 run_daily、扩 notify）。
- §6.1 发布+置顶加精 → Task 2 完整实现（含撤顶旧/置顶新、仅洪彦）。
- §6.2 教研参与+留言 → Task 1 完整实现（未开始筛选、无需邀请码、随机 5 条）。
- §6.3 路径适配 → Task 1/2 用 `os.path.dirname(__file__)`；去 `refresh_cookies` 依赖；chrome 改 venv chromium + `--disable-dev-shm-usage`。
- §6.4 定时编排 → Task 4 完整 run_daily.sh（五步顺序 + 四态捕获）。
- §6.5 推送扩展 → Task 5 扩 notify 两参数 + 两行。
- §8 验证 → Task 6（本地语法）+ Task 7（服务器 e2e + 微信 + 后台）。
- §9 风险 → 仅参与一个活动、仅操作洪彦话题，已在 Task 1/2 实现中体现。

**2. 占位扫描：** 无 TBD/TODO/"类似 Task N"。每步含完整代码或确切命令。通过。

**3. 类型一致性：** `run(count, dry_run, aid)` / `manage_action(s, csrf, ids, action)` / `status_tag(text, ok)` / `desc_row(label, value_html)` 签名在 Task 1/2/5 中前后一致。`args.topic_status`/`args.activity_status` 在 Task 5 定义并被 `build_html` 使用。通过。

**执行方式待用户选择（见下方）。**
