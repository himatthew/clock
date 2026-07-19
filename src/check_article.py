# -*- coding: utf-8 -*-
"""仅检查: 当天文章是否已发布到「教师文章」列表(不提交)。支持一天多篇。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_article_playwright import (parse_cookies, find_article, parse_article,
                                        today_str, POST_URL, UA)
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
COOKIES = os.path.join(HERE, "..", "cookies.txt")


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else today_str()
    arts = find_article(date)          # 返回当天所有 md 路径(可能多篇)
    if not arts:
        print(f"[检查] 未找到 {date} 的文章 md"); return 1
    titles = [parse_article(a)[0] for a in arts]
    ck = open(COOKIES).read().strip()
    all_hit = True
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(user_agent=UA)
        ctx.add_cookies(parse_cookies(ck))
        page = b.new_page()
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        no_perm = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        if "无权限" in no_perm:
            print("[检查] add 页无权限(cookie 可能过期), 无法可靠判断"); b.close(); return 2
        verify_url = "https://ms.zjer.cn/index.php?r=studio/post/list&sid=2174&cid=60423"
        page.goto(verify_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        for _ in range(6):
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(600)
        txt = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        for t in titles:
            probe = t[:10]
            hit = probe in txt
            all_hit = all_hit and hit
            print(f"[检查] 标题前10字='{probe}' 列表命中={hit}")
        b.close()
    return 0 if all_hit else 1


if __name__ == "__main__":
    sys.exit(main())
