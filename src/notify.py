#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PushPlus 微信推送通知 (之江汇每日自动发布结果)

读取同目录 .env 中的 PUSHPLUS_TOKEN，调用 https://www.pushplus.plus/send
正文用 antd 设计语言风格的 HTML 卡片 (template=html) 渲染。
token 缺失时退出码 2，推送失败退出码 1。

用法:
  python3 notify.py --date 2026-07-17 \
      --cookie-status "成功" \
      --upload-status "成功" \
      --resources "10_000_Miles_Away" \
      --detail "$(tail -n 25 cron.log)"
"""
import argparse
import json
import os
import re
import sys
import urllib.request


PUSHPLUS_URL = "https://www.pushplus.plus/send"

# antd 设计令牌
C_PRIMARY = "#1677ff"
C_SUCCESS = "#52c41a"
C_SUCCESS_TEXT = "#389e0d"
C_SUCCESS_BG = "#f6ffed"
C_SUCCESS_BD = "#b7eb8f"
C_ERROR = "#ff4d4f"
C_ERROR_TEXT = "#cf1322"
C_ERROR_BG = "#fff1f0"
C_ERROR_BD = "#ffa39e"
C_TEXT = "rgba(0,0,0,0.88)"
C_TEXT_2 = "rgba(0,0,0,0.45)"
C_BORDER = "#f0f0f0"
C_BORDER_2 = "#f5f5f5"
C_FILL = "#fafafa"
FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', "
        "Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif")
MONO = ("'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace")


def load_env(path):
    """极简 .env 解析: KEY=VALUE, 忽略注释与空行, 去引号。"""
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def send(token, title, content, template="html", to=None):
    data = {
        "token": token,
        "title": title,
        "content": content,
        "template": template,
    }
    if to:
        data["to"] = to
    req = urllib.request.Request(
        PUSHPLUS_URL,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)
    except Exception as e:  # noqa: BLE001
        return {"code": -1, "msg": f"请求异常: {e}"}


def escape_html(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_resource_label(resources):
    """把逗号/换行分隔的资源名整理成「、」连接的展示串。"""
    if not resources or not resources.strip():
        return "今日资源"
    parts = [p.strip() for p in re.split(r"[,，\n]", resources) if p.strip()]
    return "、".join(parts) if parts else "今日资源"


def status_tag(text, ok):
    color = C_SUCCESS_TEXT if ok else C_ERROR_TEXT
    bg = C_SUCCESS_BG if ok else C_ERROR_BG
    bd = C_SUCCESS_BD if ok else C_ERROR_BD
    return (f'<span style="display:inline-block;padding:1px 8px;border-radius:4px;'
            f'font-size:12px;line-height:20px;background:{bg};border:1px solid {bd};'
            f'color:{color};">{escape_html(text)}</span>')


def desc_row(label, value_html):
    return (f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:9px 0;border-bottom:1px solid {C_BORDER_2};font-size:13px;">'
            f'<span style="color:{C_TEXT_2};">{escape_html(label)}</span>'
            f'<span style="color:{C_TEXT};text-align:right;">{value_html}</span></div>')


def build_html(args, headline, emoji, ok, rows):
    header_bg = C_SUCCESS if ok else C_ERROR
    text_color = C_SUCCESS_TEXT if ok else C_ERROR_TEXT

    detail_html = ""
    if args.detail:
        detail_html = (
            f'<div style="margin-top:14px;padding:10px 12px;background:{C_FILL};'
            f'border:1px solid {C_BORDER};border-radius:6px;font-size:12px;'
            f'color:{C_TEXT_2};white-space:pre-wrap;word-break:break-all;'
            f'font-family:{MONO};line-height:1.6;">{escape_html(args.detail)}</div>'
        )

    return f"""<div style="font-family:{FONT};color:{C_TEXT};max-width:480px;margin:0 auto;
box-sizing:border-box;">
  <div style="background:{header_bg};border-radius:8px 8px 0 0;padding:14px 18px;color:#fff;
box-sizing:border-box;">
    <div style="font-size:15px;font-weight:600;">{emoji} 毛毛打卡通知 · {escape_html(args.date or '今日')}</div>
  </div>
  <div style="background:#fff;border:1px solid {C_BORDER};border-top:none;
border-radius:0 0 8px 8px;padding:16px 18px;box-sizing:border-box;">
    <div style="font-size:15px;font-weight:600;margin-bottom:14px;color:{text_color};
word-break:break-all;">{escape_html(headline)}</div>
    {''.join(rows)}
    {detail_html}
  </div>
</div>"""


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="PushPlus 微信推送 (antd 风)")
    ap.add_argument("--title", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--cookie-status", default="未知")
    ap.add_argument("--upload-status", default="未知")
    ap.add_argument("--resources", default="", help="当天发布的资源名(逗号分隔多个)")
    ap.add_argument("--topic-status", default="未知", help="话题发布状态(成功/失败)")
    ap.add_argument("--activity-status", default="未知", help="教研参与状态(成功/失败)")
    ap.add_argument("--article-status", default="未知", help="文章发布状态(成功/失败)")
    ap.add_argument("--no-article", action="store_true", help="隐藏 文章发布 行")
    ap.add_argument("--no-topic", action="store_true", help="隐藏 话题发布 行")
    ap.add_argument("--no-activity", action="store_true", help="隐藏 教研参与 行")
    ap.add_argument("--headline", default="", help="自定义正文主文案(覆盖默认资源文案)")
    ap.add_argument("--resource-only", action="store_true",
                    help="只显示 工作室/Cookie/资源 三行(资源拆页上传任务专用)")
    ap.add_argument("--no-resource", action="store_true",
                    help="隐藏 资源上传 行(资源改由独立拆页任务上报时, 主任务用)")
    ap.add_argument("--detail", default="")
    ap.add_argument("--env-file", default=os.path.join(here, "..", ".env"))
    args = ap.parse_args()

    env = load_env(args.env_file)
    primary = env.get("PUSHPLUS_TOKEN") or os.environ.get("PUSHPLUS_TOKEN")
    if not primary:
        print("ERROR: 未找到 PUSHPLUS_TOKEN (.env 或环境变量)", file=sys.stderr)
        sys.exit(2)
    friend = env.get("PUSHPLUS_FRIEND_TOKEN") or os.environ.get("PUSHPLUS_FRIEND_TOKEN")

    # 收件人: (发送用 token, to 参数)
    # 主: token=主, to=None(仅自己)
    # 好友: token=主, to=好友令牌  (PushPlus 好友推送走 to 参数, 见官方文档)
    recipients = [(primary, None)]
    if friend:
        recipients.append((primary, friend))

    def sec_ok(s):
        return "成功" in s and "失败" not in s

    cookie_ok = sec_ok(args.cookie_status)
    upload_ok = sec_ok(args.upload_status)
    topic_ok = sec_ok(args.topic_status)
    activity_ok = sec_ok(args.activity_status)
    article_ok = sec_ok(args.article_status)

    res_label = build_resource_label(args.resources)

    # 整体成功判定: 所有展示分区状态都为成功
    shown_oks = [cookie_ok]
    if not args.resource_only and not args.no_resource:
        shown_oks.append(upload_ok)
    if not args.resource_only and not args.no_topic:
        shown_oks.append(topic_ok)
    if not args.resource_only and not args.no_activity:
        shown_oks.append(activity_ok)
    if not args.resource_only and not args.no_article:
        shown_oks.append(article_ok)
    overall_ok = all(shown_oks)

    # 标题与整体成功判定一致: 任一分区分失败即整体失败标题(失败不再报"下发完毕"误导)
    title = args.title or ("毛毛小主下发完毕" if overall_ok
                           else "警告！推送失败，请小主排查")

    # 构造状态行: --resource-only 仅 Cookie/资源(隐藏其余); 各 --no-* 单独隐藏对应行
    rows = [desc_row("工作室", "陈晓雯名师工作室 (sid=2174)"),
            desc_row("Cookie 刷新", status_tag(args.cookie_status, cookie_ok))]
    if not args.resource_only:
        if not args.no_resource:
            rows.append(desc_row("资源上传", status_tag(args.upload_status, upload_ok)))
        if not args.no_topic:
            rows.append(desc_row("话题发布", status_tag(args.topic_status, topic_ok)))
        if not args.no_activity:
            rows.append(desc_row("教研参与", status_tag(args.activity_status, activity_ok)))
        if not args.no_article:
            rows.append(desc_row("文章发布", status_tag(args.article_status, article_ok)))

    # 正文主文案
    if args.headline:
        headline = args.headline
    elif not args.resource_only and not args.no_resource:
        headline = (f"成功！毛毛小主！资源 {res_label} 已发布成功" if upload_ok
                    else f"失败～毛毛小主 资源 {res_label} 发布失败")
    else:
        headline = ("成功！毛毛小主！今日任务已完成" if overall_ok
                    else "失败～毛毛小主 今日有任务未通过")

    emoji = "✅" if overall_ok else "⚠️"

    content = build_html(args, headline, emoji, overall_ok, rows)

    # 旁路本机 aTrust 隧道代理 (pushplus 直连即可)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)

    ok = True
    for i, (tk, to) in enumerate(recipients):
        tag = "主" if i == 0 else f"好友{i}"
        r = send(tk, title, content, template="html", to=to)
        print(f"[{tag}] {json.dumps(r, ensure_ascii=False)}")
        if i == 0 and r.get("code") != 200:
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
