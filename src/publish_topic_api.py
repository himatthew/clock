#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
之江汇教育广场 (陈晓雯名师工作室 sid=2174) 话题发布 - 接口直发版
GET 发布页抓 _csrf -> POST {title, content, _csrf} -> 判据成功。

比 Playwright 爬页面快得多, 且绕过了 UEditor 的 isReady 永不置位问题。
用法:
  # 推荐: 读 topics_config.json 里「当天」的话题自动发
  python3 publish_topic_api.py cookies.txt

  # 指定配置文件 / 看某天的话题(不实际发送)
  python3 publish_topic_api.py cookies.txt --config my_topics.json
  python3 publish_topic_api.py cookies.txt --date 2026-07-15 --dry-run

  # 仍支持旧的显式/params 写法
  python3 publish_topic_api.py cookies.txt --title "标题" --content "内容"
  python3 publish_topic_api.py cookies.txt --params topic.json
  python3 publish_topic_api.py cookies.txt --title "T" --content "C" --dry-run
"""
import os, re, json, argparse, requests
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from topic_config import resolve_topic, list_topics, _default_config_path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_URL = "https://ms.zjer.cn/index.php?r=studio/topic/add&sid=2174"


def log(*a):
    print(*a, flush=True)


def load_cookie(path):
    return re.sub(r"\s+", " ", open(path, encoding="utf-8").read().strip()).strip()


def grab_csrf(session, cookie, url):
    h = {"Cookie": cookie, "User-Agent": UA}
    r = session.get(url, headers=h, timeout=30)
    html = r.text
    m = re.search(r'name=["\']?_csrf["\']?\s+value=["\']([^"\']+)', html)
    if not m:
        m = re.search(r'YII_CSRF_TOKEN["\s:]+([^"\';<>\s]{20,})', html)
    return m.group(1) if m else ""


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
    ap.add_argument("--dry-run", action="store_true", help="只打印 POST 数据, 不实际发送")
    args = ap.parse_args()

    if args.list:
        cp = args.config or _default_config_path()
        rows = list_topics(cp)
        if not rows:
            raise SystemExit(f"配置文件无话题: {cp}")
        log(f"配置文件 {cp} 中的话题:")
        for d, t in rows:
            log(f"  {d:>12}  {t}")
        return

    params = json.load(open(args.params, encoding="utf-8")) if args.params else None
    title, content, source = resolve_topic(
        config_path=args.config, override_date=args.date,
        cli_title=args.title, cli_content=args.content, params=params)
    log(f"来源: {source}")

    cookie = load_cookie(args.cookie)
    s = requests.Session()
    csrf = grab_csrf(s, cookie, args.url)
    log(f"_csrf: {csrf[:24]}..." if csrf else "未抓到 _csrf (可能该路由不校验)")

    data = {"title": title, "content": content}
    if csrf:
        data["_csrf"] = csrf

    if args.dry_run:
        log("[dry-run] 将发送的 POST 数据:")
        for k, v in data.items():
            show = v if len(v) <= 120 else v[:120] + "..."
            log(f"    {k} = {show}")
        return

    h = {"Cookie": cookie, "User-Agent": UA, "Referer": args.url,
         "Content-Type": "application/x-www-form-urlencoded"}
    r = s.post(args.url, data=data, headers=h, timeout=30, allow_redirects=False)
    body = r.text
    log(f"POST status={r.status_code}")
    loc = r.headers.get("Location", "")
    if "发布话题成功" in body or "发布成功" in body:
        log("✅ 话题发布成功")
    elif "topic/index" in loc or "topic/index" in r.url:
        log("✅ 疑似成功 (跳转到话题列表)")
    else:
        for kw in ["错误", "不能为空", "请填写", "标题", "内容"]:
            if kw in body:
                idx = body.find(kw)
                log(f"⚠️ 响应含 '{kw}': ...{body[max(0, idx - 30):idx + 40]}...")
                break
        else:
            log("❓ 未检测到明确成功标识, 请检查响应/页面 (响应前120字: %s)" % body[:120])


if __name__ == "__main__":
    main()
