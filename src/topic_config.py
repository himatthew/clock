#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
话题配置加载器 —— 被 publish_topic_api.py / publish_topic_playwright.py 复用。

配置文件 topics_config.json 结构(三种都支持):
  1) 按日期排期(推荐):
     {
       "topics": [
         {"date": "2026-07-14", "title": "夏天最适合听什么音乐", "content": "音乐让夏天不一样"},
         {"date": "2026-07-15", "title": "..."， "content": "..."}
       ]
     }
  2) 带默认兜底: 上面的 topics 里没匹配到当天时, 用 default
     { "default": {"title": "...", "content": "..."}, "topics": [ ... ] }
  3) 扁平单条(每天手动改这一个):
     {"title": "...", "content": "..."}

解析优先级: CLI --title/--content  >  --params json  >  配置文件(按日期匹配, 否则 default)
"""
import json
import os
import datetime


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def _default_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "topics_config.json")


def _load(config_path):
    if not config_path or not os.path.exists(config_path):
        return None
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def list_topics(config_path=None):
    """返回配置里所有话题的 [(date, title)] , 供 --list 调试。"""
    cfg = _load(config_path or _default_config_path())
    if not cfg:
        return []
    rows = []
    for it in (cfg.get("topics") or []):
        rows.append((it.get("date", "?"), it.get("title", "")))
    d = cfg.get("default")
    if d:
        rows.append(("(default)", d.get("title", "")))
    if not rows and cfg.get("title"):
        rows.append(("(flat)", cfg.get("title", "")))
    return rows


def resolve_topic(config_path=None, override_date=None,
                  cli_title=None, cli_content=None, params=None):
    """
    返回 (title, content, source_str)。
    优先级: 命令行 --title/--content  >  --params json  >  配置文件
    """
    # 1) 最高优先级: 命令行同时给了 title 和 content
    if cli_title and cli_content:
        return cli_title, cli_content, "CLI --title/--content"

    # 2) --params json 同时含 title 和 content
    if isinstance(params, dict) and params.get("title") and params.get("content"):
        return params["title"], params["content"], "params json"

    # 3) 配置文件
    cfg = _load(config_path or _default_config_path())
    if cfg:
        date_key = override_date or today_str()
        # 3a) 在 topics 列表里按日期匹配当天
        for it in (cfg.get("topics") or []):
            if it.get("date") == date_key:
                return it.get("title"), it.get("content"), f"config[{date_key}]"
        # 3b) 没匹配到当天 -> default
        d = cfg.get("default")
        if d and d.get("title") and d.get("content"):
            return d["title"], d["content"], "config default"
        # 3c) 扁平单条
        if cfg.get("title") and cfg.get("content"):
            return cfg["title"], cfg["content"], "config flat"

    raise SystemExit(
        "未找到话题内容: 请传入 --title/--content、--params json, "
        "或在配置文件中提供当天(date=%s)或 default 话题" % (override_date or today_str())
    )
