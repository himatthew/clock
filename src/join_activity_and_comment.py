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
    "COOKIES_FILE": os.path.join(HERE, "..", "cookies.txt"),
    "DOCX": os.path.join(HERE, "..", "data", "提问研讨留言库.docx"),
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
                return None  # 无任务
        print(f"[教研参与] 目标活动 aid={target_aid} 《{target_title}》")
        if dry_run:
            chosen = random.sample(messages, count)
            print("[dry-run] 将发布:")
            for i, m in enumerate(chosen, 1):
                print(f"   {i}. {m}")
            browser.close()
            return (0, 0, True)  # dry-run 视为成功
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
        return (ok_count, len(chosen), True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5, help="留言条数(默认5)")
    ap.add_argument("--dry-run", action="store_true", help="只预览不操作")
    ap.add_argument("--aid", default=None, help="指定活动 aid")
    args = ap.parse_args()
    res = run(count=args.count, dry_run=args.dry_run, aid=args.aid)
    # 退出码: 无未参与活动(None)=0; 有活动但留言未全部成功=1; 全部成功=0
    if res is None:
        sys.exit(0)
    ok_count, total, _ = res
    sys.exit(0 if ok_count == total else 1)
