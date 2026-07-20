#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""之江汇名师工作室(ms.zjer.cn) —— 话题批量发布 + 置顶/加精 管理
流程:
  1. 读 topics_config.json, 按 date==今天 匹配(支持当天多条, 即每日批量发布)
  2. 对每条做质量校验(标题/正文长度、领域相关性), 不合格跳过
  3. 逐条 Playwright 发布, 收集新 id
  4. 只把最后一条置顶+加精, 撤掉洪彦名下其他置顶话题
Cookie 由 run_daily.sh 第一步 refresh_cookie.py 维护(本脚本只读 cookies.txt)。

话题内容由 AI 在本地(WorkBuddy)预先生成并落库到 topics_config.json,
运行时不再调用大模型, 仅按计划批量发布, 保证稳定与可控。
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

# 领域关键词(音乐/教育/教学三类), 用于生成内容的质量兜底校验
DOMAIN_WORDS = [
    "音乐", "教育", "教学", "学生", "课堂", "小学", "老师", "教师", "孩子", "班级", "家长", "作业",
    "唱歌", "歌唱", "节奏", "乐器", "合唱", "欣赏", "柯达伊", "奥尔夫", "达尔克罗兹", "体态律动",
    "识谱", "旋律", "民歌", "戏曲", "创作", "聆听", "演唱", "发声", "音准", "多声部", "游戏",
    "情境", "项目式", "跨学科", "评价", "绘本", "技术", "AI", "数字化", "素养", "课程",
    "教案", "教研", "成长", "公开课", "合作", "学习",
]


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
    """返回当天所有匹配话题 [(title, content), ...]; 无则 fallback default(单条)。"""
    with open(CONFIG["TOPICS_CONFIG"], encoding="utf-8") as f:
        cfg = json.load(f)
    dk = today_str()
    items = [(it["title"], it["content"]) for it in cfg.get("topics", [])
             if it.get("date") == dk]
    if items:
        return items
    d = cfg.get("default")
    if d:
        return [(d["title"], d["content"])]
    raise SystemExit(f"配置里无 {dk} 的话题, 也无 default")


def validate_topic(title, content):
    """质量校验: 非空、长度合理、命中领域词、非模板雷同。返回 (ok, reason)。"""
    if not title or not content:
        return False, "标题或正文为空"
    if not (4 <= len(title) <= 40):
        return False, f"标题长度异常({len(title)})"
    if not (30 <= len(content) <= 600):
        return False, f"正文长度异常({len(content)})"
    hit = sum(1 for w in DOMAIN_WORDS if w in title + content)
    if hit < 2:
        return False, f"领域相关性不足(命中{hit})"
    if content.strip() == title.strip():
        return False, "正文与标题雷同"
    return True, "ok"


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
    items = load_topic_config()
    print(f"[话题] {today_str()}: 当日待发布 {len(items)} 个")
    cookies = load_cookies(CONFIG["COOKIES_FILE"])
    s = new_session(cookies)
    csrf = get_csrf(s)
    if not csrf:
        print("[CSRF] ❌ 未获取到, 中止")
        sys.exit(1)
    new_ids = []
    for i, (title, content) in enumerate(items, 1):
        ok, why = validate_topic(title, content)
        if not ok:
            print(f"[话题] ⚠️ 第{i}条质量不达标({why}), 跳过: {title}")
            continue
        print(f"[话题] ({i}/{len(items)}) {title}")
        new_id = publish_topic_playwright(title, content)
        if not new_id:
            print(f"[话题] ⚠️ 第{i}条 URL 未取到 id, 用标题回查")
            r = s.get(f"{CONFIG['BASE']}/index.php?r=studio/topic/index&sid={CONFIG['SID']}", timeout=30)
            m = re.search(r'(?:&|\?)id=(\d+)[^>]*>' + re.escape(title), r.text)
            new_id = m.group(1) if m else None
        if new_id:
            new_ids.append(new_id)
            print(f"[话题] ✅ 第{i}条 新话题 id={new_id}")
        else:
            print(f"[话题] ❌ 第{i}条 无法定位, 跳过")
    if not new_ids:
        print("[话题] ❌ 无成功发布的话题, 跳过置顶管理")
        sys.exit(1)
    # 只置顶+加精最后一条, 撤掉洪彦其他置顶话题(保持工作室置顶位整洁)
    to_top = new_ids[-1]
    print(f"[话题] 置顶管理: 仅置顶最后一条 id={to_top}, 其余洪彦置顶话题将撤顶")
    topped = get_topped_ids(s)
    authors = get_authors(s)
    hongyan_topped = [t for t in topped if authors.get(t) == CONFIG["HONGYAN_NAME"]]
    old = [t for t in hongyan_topped if t != to_top]
    if old:
        print(f"[话题] 撤顶+取消加精 旧: {old}")
        print("  撤顶:", manage_action(s, csrf, old, "untop"))
        print("  取消加精:", manage_action(s, csrf, old, "unessence"))
    else:
        print("[话题] 洪彦无其它置顶话题, 跳过撤顶")
    print(f"[话题] 置顶+加精 {to_top}")
    print("  置顶:", manage_action(s, csrf, [to_top], "top"))
    print("  加精:", manage_action(s, csrf, [to_top], "essence"))
    print("[话题] ✅ 完成")
    failed = len(items) - len(new_ids)
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
