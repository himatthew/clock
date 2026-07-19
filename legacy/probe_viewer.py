#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：用 Playwright 加载 tan8 详情页，捕获所有谱面图片请求，弄清 viewer 如何加载多页。"""
import sys, json, time
from playwright.sync_api import sync_playwright

PROXY = "http://127.0.0.1:55113"
TARGET = sys.argv[1] if len(sys.argv) > 1 else "18547"

def main():
    oss_requests = []
    all_imgs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy={"server": PROXY},
            args=["--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )
        page = ctx.new_page()
        # 监听所有网络请求，捕获 oss.tan8.com 图片
        def on_request(req):
            u = req.url
            if "oss.tan8.com" in u and any(e in u for e in (".png", ".jpg", ".jpeg", ".webp")):
                oss_requests.append(u)
        page.on("request", on_request)

        url = f"https://www.tan8.com/yuepu-{TARGET}.html"
        print(f"[*] 加载 {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print(f"    goto 警告: {e}")
        # 等待 viewer 初始化
        page.wait_for_timeout(3000)

        # 抓取当前 DOM 中所有 img src
        all_imgs = page.eval_on_selector_all(
            "img",
            "els => els.map(e => ({src: e.getAttribute('src'), ds: e.getAttribute('data-src'), cls: e.className, id: e.id}))",
        )
        # 过滤含 prev_ 的
        prev_imgs = [i for i in all_imgs if i["src"] and "prev_" in i["src"]]

        print(f"\n=== 初始加载后，oss 图片请求数: {len(oss_requests)} ===")
        for u in oss_requests[:60]:
            print("  REQ", u)

        print(f"\n=== DOM 中 prev_ 图片 (src) 数: {len(prev_imgs)} ===")
        for i in prev_imgs[:60]:
            print("  IMG", i["src"], "| cls=", i["cls"])

        # 找可能的翻页按钮 / 缩略图条，尝试点击遍历
        # 常见：.next, #next_page, 含 "下一" 的按钮
        clickable_hints = page.eval_on_selector_all(
            "a,button,div,span,li",
            "els => els.filter(e => {"
            "  const t = (e.textContent||'').trim();"
            "  const c = (e.className||'').toString();"
            "  return /下一页|上一页|下一|上一|第.*页|缩略|全部/.test(t+c) && t.length<=12;"
            "}).map(e => ({tag:e.tagName, txt:(e.textContent||'').trim().slice(0,20), cls:(e.className||'').toString().slice(0,40)}))",
        )
        print(f"\n=== 可能的翻页/缩略图控件: {len(clickable_hints)} ===")
        for h in clickable_hints[:30]:
            print("  CTRL", h)

        # 尝试点击缩略图条里的所有元素，看能否触发更多 oss 请求
        before = len(oss_requests)
        try:
            thumbs = page.query_selector_all(".piano_thumb_list img, .thumbnail img, .small_img img, [class*=thumb] img")
            print(f"\n[*] 找到缩略图 img: {len(thumbs)} 个，逐个点击…")
            for t in thumbs[:50]:
                try:
                    t.click(timeout=1500)
                    page.wait_for_timeout(400)
                except Exception:
                    pass
        except Exception as e:
            print("  缩略图点击异常:", e)
        page.wait_for_timeout(2000)
        after = len(oss_requests)
        print(f"[*] 点击缩略图后新增 oss 请求: {after-before}")

        # 保存页面 HTML 供分析
        html = page.content()
        with open(f"/tmp/tan8_{TARGET}.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[*] 已保存 HTML -> /tmp/tan8_{TARGET}.html ({len(html)} bytes)")

        browser.close()

    # 去重排序输出
    uniq = sorted(set(oss_requests))
    print(f"\n=== 去重后 oss 图片 URL 总数: {len(uniq)} ===")
    for u in uniq:
        print(u)

if __name__ == "__main__":
    main()
