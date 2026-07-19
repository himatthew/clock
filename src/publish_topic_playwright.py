#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
之江汇教育广场 (陈晓雯名师工作室 sid=2174) 话题发布 - Playwright 版
处理 UEditor 编辑器 (轮询实例 key + setContent, 绕过 isReady 永不置位),
填标题/内容后点 #topic_butt 发布。默认 headless 自动化; --no-headless 弹窗可视化。

用法:
  # 推荐: 读 topics_config.json 里「当天」的话题自动发
  python3 publish_topic_playwright.py cookies.txt
  # 可视化排查当天话题:
  python3 publish_topic_playwright.py cookies.txt --no-headless

  # 指定配置文件 / 看某天的话题
  python3 publish_topic_playwright.py cookies.txt --config my_topics.json
  python3 publish_topic_playwright.py cookies.txt --date 2026-07-15

  # 仍支持旧的显式/params 写法
  python3 publish_topic_playwright.py cookies.txt --title "标题" --content "内容"
  python3 publish_topic_playwright.py cookies.txt --params topic.json
"""
import os, json, argparse
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
from topic_config import resolve_topic, list_topics, _default_config_path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_URL = "https://ms.zjer.cn/index.php?r=studio/topic/add&sid=2174"


def log(*a):
    print(*a, flush=True)


def parse_cookies(s):
    c = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        name, value = part.split("=", 1) if "=" in part else (part, "")
        dom = ".henan.smartedu.cn" if "henan.smartedu.cn" in name else ".zjer.cn"
        c.append({"name": name.strip(), "value": value.strip(), "domain": dom, "path": "/"})
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cookie", help="cookies.txt 路径")
    ap.add_argument("url", nargs="?", default=DEFAULT_URL, help="话题发布页 URL")
    ap.add_argument("--title", default=None)
    ap.add_argument("--content", default=None)
    ap.add_argument("--params", default=None, help="json 文件, 含 {title, content} (优先级低于 --title/--content, 高于配置文件)")
    ap.add_argument("--config", default=None, help="话题配置文件 (默认 topics_config.json)")
    ap.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD 取话题 (默认当天, 用于测试/补发)")
    ap.add_argument("--list", action="store_true", help="列出配置文件里全部话题后退出")
    ap.add_argument("--headless", action="store_true", default=True, help="默认无头自动化")
    ap.add_argument("--no-headless", dest="headless", action="store_false", help="弹窗可视化排查")
    args = ap.parse_args()

    if args.list:
        cp = args.config or _default_config_path()
        rows = list_topics(cp)
        if not rows:
            raise SystemExit(f"配置文件无话题: {cp}")
        print(f"配置文件 {cp} 中的话题:")
        for d, t in rows:
            print(f"  {d:>12}  {t}")
        return

    params = json.load(open(args.params, encoding="utf-8")) if args.params else None
    title, content, source = resolve_topic(
        config_path=args.config, override_date=args.date,
        cli_title=args.title, cli_content=args.content, params=params)
    print(f"来源: {source}")

    cookie = open(args.cookie, encoding="utf-8").read().strip()
    log(f"headless={args.headless}")

    with sync_playwright() as p:
        b = p.chromium.launch(headless=args.headless, args=["--no-sandbox"])
        ctx = b.new_context(user_agent=UA)
        ctx.add_cookies(parse_cookies(cookie))
        page = ctx.new_page()

        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        log("page loaded:", page.title())
        page.fill("#title", title)
        log("filled title")

        # UEditor 实例初始化: 轮询任意实例, 不要求 isReady
        ed = page.evaluate("""() => {
            const start = Date.now();
            while (Date.now() - start < 25000) {
                if (window.UE && window.UE.instants) {
                    const keys = Object.keys(UE.instants);
                    if (keys.length) {
                        const k = keys[0];
                        const inst = UE.instants[k];
                        return {key: k, hasSetContent: !!inst.setContent};
                    }
                }
                const e = new Date(); while (new Date() - e < 200) {}
            }
            return null;
        }""")
        log(f"ueditor: {ed}")

        if ed and ed.get("hasSetContent"):
            res = page.evaluate(
                """([t, k]) => { try { UE.instants[k].setContent(t); return 'ok'; } catch(e){ return 'err:'+e; } }""",
                [content, ed["key"]])
            log(f"setContent={res}")
        else:
            page.evaluate(
                """(t) => { const ta = document.querySelector('textarea[name=content]'); if (ta) ta.value = t; }""",
                content)
            log("textarea fallback (无 ueditor api)")

        page.wait_for_timeout(1500)

        # 发布
        page.click("#topic_butt")
        log("clicked publish")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            log(f"netidle note: {e}")
        page.wait_for_timeout(3000)

        final = page.url
        log(f"final url: {final}")
        body = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        for kw in ["成功", "失败", "错误", "请填写", "不能为空", "已发布", "发表"]:
            if kw in body:
                log(f"body keyword: '{kw}'")
        if "topic/index" in final:
            log("✅ 疑似成功 (跳转到话题列表)")
        b.close()


if __name__ == "__main__":
    main()
