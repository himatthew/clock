#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源配置加载器 —— 被 publish_resource_api.py / publish_resource_playwright.py 复用。

配置文件 resources_config.json 结构(三种都支持):
  1) 按日期排期(推荐):
     {
       "fixed": { "classid":"22", "subject":"jcsub20", ... },   # 工作室固定字段(可选, 覆盖默认)
       "resources": [
         {"date":"2026-07-14", "file":"/path/课件.pptx", "title":"课件名", "intro":"简介(可省,默认=title)"},
         ...
       ]
     }
  2) 带默认兜底: resources 里没匹配到当天时, 用 default
     { "default": {"file":"...","title":"..."}, "resources":[ ... ] }
  3) 扁平单条(每天手动改这一个):
     {"file":"...","title":"..."}

解析优先级: 命令行 --file/--title  >  配置文件(按 date==运行日 匹配, 否则 default)
返回字段 = {**DEFAULT_FIXED, **config.fixed, **per_resource}  (per_resource 可覆盖任何固定字段)

可读名映射(重点!): classid / original / parentId / period / subject / public_status 这些字段,
配置里既可写「原始 value」(如 classid=22), 也可写「可读中文名」(如 classid=课件)。加载时会自动
把中文名翻译成页面真实 value。其中 classid/original/parentId/period/subject 是页面可见的
选项列表(全部可选项见下方 *_OPTIONS 常量, 或运行 inspect_resource_options.py 从页面抓取)。
public_status 是页面下拉(已抓取真实 3 项: 开放下载/仅限成员下载/不可下载)。
edition(教材目录) 不是页面选型列表——它是 hidden 字段, 由页面级联选择后写入 editionid/editionname;
工作室场景固定填「其它」(editionid=ms_other_330000, 已实测验证), 故用映射表固定, 不进选项清单。
"""
import json
import os
import re
import datetime


# ===== 各字段「可读名 -> 页面真实 value」映射 =====
# 由 inspect_resource_options.py 从上传页抓取(2026-07). 站点若增改选项, 重跑该脚本更新此处.

# 资源类型
CLASSID_OPTIONS = {
    "微课": "24", "学案": "20", "教案": "21", "课件": "22", "素材": "23",
    "试题": "2", "说课": "25", "讲座": "27", "课题论文": "7", "其它": "8",
}

# 属性
ORIGINAL_OPTIONS = {
    "本人原创": "0", "工作室成员原创": "2", "授权转载": "1",
}

# 学段
PERIOD_OPTIONS = {
    "学前": "xq", "小学": "xx", "初中": "cz", "高中": "pg", "中职": "zz", "特殊教育": "tj",
}

# 教材目录. 配置里写一个可读名 edition, 加载时展开为表单的 editionid + editionname 两个字段.
# 工作室固定用「其它」. 站点其它教材目录如需支持, 在此补充「显示名 -> value」.
EDITION_OPTIONS = {
    "其它": "ms_other_330000",
}

# 开放状态(是否开放下载). 真实下拉选项(2026-07 抓取): 1=开放下载 / 2=仅限成员下载 / 0=不可下载
PUBLIC_STATUS_OPTIONS = {
    "开放下载": "1", "仅限成员下载": "2", "不可下载": "0",
}

# 学科(小学). 注意: "音乐"=jcsub20(常用), "艺术·音乐"=fd88cf... 是另一项, 别选错.
SUBJECT_OPTIONS = {
    "语文": "jcsub01", "数学": "jcsub02", "英语": "jcsub03",
    "艺术·美术": "bfc57021a3194d6b838ca8a1c9baffb8",
    "艺术·音乐": "fd88cf852b5a421ba533966a9e6aef62",
    "道德与法治": "SUB53", "科学": "jcsub16", "美术": "jcsub18",
    "体育与健康": "jcsub19", "音乐": "jcsub20", "信息技术": "jcsub21",
    "信息科技": "SUB57", "心理健康": "2ec954f1fabe49389cf3cacf824b5fdd",
    "劳动教育": "f8714dddb6594971b3d5382844e41eba",
    "综合实践活动": "jcsub23", "科技制作活动": "jcsub29", "生活与科技": "jcsub31",
    "班主任": "SUB19_ZJ", "安全教育": "SUB50", "传统文化": "SUB49",
    "少先队活动": "self_zj_016",
}

# 工作室分类(该工作室专属分类树, 提交时 rtype 会自动同步为此 id)
PARENTID_OPTIONS = {
    "（教材与教学设计）原本性艺术教育": "zhuantiziyuanidAAAAAAAA4178",
    "（即兴原创微音乐剧）原本性艺术教育": "zhuantiziyuanidAAAAAAAA4183",
    "（作品展示）工作室成员学校参加各级艺术节": "zhuantiziyuanidAAAAAAAA4188",
    "（视频资源）原本性艺术教育": "zhuantiziyuanidAAAAAAAA4194",
    "（理论研究）原本性艺术教育": "zhuantiziyuanidAAAAAAAA4196",
    "乐器工坊": "zhuantiziyuanidAAAAAAAA4568",
    "器乐教学系列课程": "805470220b7233ce35d9c6fdc1eed76a",
    "单元整体性设计": "ec8028bab72abd2beaaba6f564efb0ff",
    "PPT": "db1a78ebac1d2c2f2970bbf81f0d1a61",
    "综合资源": "a14c5ca55abf3be32f4f83e543311b74",
    "中小学音乐素养生长命题设计": "9e13d2b501a8e35eca291c4a6db2d5fb",
    "高中舞蹈教材音频或视频": "62c71091bfd565bd943455e13e1c2bdb",
    "高中舞蹈教材教案": "cdf44bffeb14561acc2cc2ae9c054de9",
    "高中舞蹈教材": "0013f55c2c45c0e436ff73c6b32fe460",
    "高中音乐教材音频或视频": "2e1b5a7ea14ee8d9f6e101b4eb47f92d",
    "高中音乐教材教案": "52f35d1be2b9ad7d347271ba787b46c7",
    "高中音乐教材": "dffbe27e9e1dc3d2534e152e29e5c59e",
    "人音版初中艺术.音乐音频、视频": "7fc8926d46144840e79e1bd04e9017bf",
    "人音版初中艺术.音乐教材": "7e1b2aed27f7eeeaa43e02cfc7183e8a",
    "人音版小学艺术.音乐教材": "2c18b0744617a88550d184e186ddc584",
    "人音版初中艺术.音乐教案": "9310966f344384e0d388439522b53da3",
    "人音版小学教材音频、视频": "b626ee01e5561353742e5861e534f4ea",
    "人音版小学艺术.音乐教案": "ce39990694d6e77dcdc76b69e9e14106",
}

# 字段 -> 映射表(单字段: 可读名 -> value, 原地翻译)
_FIELD_MAPS = {
    "classid": CLASSID_OPTIONS,
    "original": ORIGINAL_OPTIONS,
    "period": PERIOD_OPTIONS,
    "subject": SUBJECT_OPTIONS,
    "parentId": PARENTID_OPTIONS,
    "public_status": PUBLIC_STATUS_OPTIONS,
}


def normalize_fields(fields):
    """把可读中文名翻译为页面真实 value。若已是原始 value(不在映射 key 里)则原样保留 -> 兼容旧配置。
    - classid/original/parentId/period/subject/public_status: 原地翻译。
    - edition: 一个可读名, 展开为表单需要的 editionid + editionname 两个字段。
    - parentId 解析后自动同步 rtype(提交时 onExcute() 要求 rtype==parentId)。
    """
    for key, m in _FIELD_MAPS.items():
        v = fields.get(key)
        if v is None:
            continue
        v = str(v).strip()
        fields[key] = m.get(v, v)  # 命中中文名->value; 否则原样(视为已是 value)
    # 教材目录: edition(可读名) -> editionid + editionname
    ed = fields.pop("edition", None)
    if ed is not None:
        ed = str(ed).strip()
        fields["editionid"] = EDITION_OPTIONS.get(ed, ed)  # 命中->value; 否则视为已是 value
        fields["editionname"] = ed                          # 显示名即可读名本身
    if fields.get("parentId"):
        fields["rtype"] = fields["parentId"]
    return fields


# 工作室固定表单字段(默认). 配置 fixed 段可覆盖其中任意项. 可写 value 或可读中文名.
DEFAULT_FIXED = {
    "classid": "课件",                                     # 资源类型
    "period": "小学",                                      # 学段
    "subject": "音乐",                                     # 学科(注意别写成"艺术·音乐")
    "parentId": "PPT",                                     # 工作室分类
    "edition": "其它",                                     # 教材目录(自动展开为 editionid + editionname)
    "public_status": "开放下载",                           # 开放状态
    "pricing": "0",                                        # 0 分
    "original": "授权转载",                                # 属性(授权转载)
    "original_author": "佚名",                             # 作者
    "is_research": "10",
    "rtype": "PPT",                                        # 提交前 onExcute() 会把它设为 parentId(自动同步)
    "cid": "", "rcolumn": "", "folderId": "",
    "volumeid": "", "volumename": "",
    "chapterids": "", "chaptername": "",
}


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def _default_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "resources_config.json")


def _load(config_path):
    if not config_path or not os.path.exists(config_path):
        return None
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def list_resources(config_path=None):
    """返回 [(date, title, file)] , 供 --list 调试。"""
    cfg = _load(config_path or _default_config_path())
    if not cfg:
        return []
    rows = []
    for it in (cfg.get("resources") or []):
        rows.append((it.get("date", "?"), it.get("title", ""), it.get("file", "")))
    d = cfg.get("default")
    if d:
        rows.append(("(default)", d.get("title", ""), d.get("file", "")))
    return rows


def resolve_resource(config_path=None, override_date=None,
                     cli_file=None, cli_title=None, cli_intro=None):
    """
    返回 (fields_dict, source_str)。
    fields_dict = {**DEFAULT_FIXED, **config.fixed, **per_resource}
    优先级: 命令行 --file/--title  >  配置文件(按日期匹配, 否则 default)
    """
    # 1) 最高优先级: 命令行同时给了 file 和 title
    if cli_file and cli_title:
        fields = dict(DEFAULT_FIXED)
        cfg = _load(config_path or _default_config_path())
        if cfg and cfg.get("fixed"):
            fields.update({k: v for k, v in cfg["fixed"].items() if not k.startswith("_")})
        fields["file"] = cli_file
        fields["title"] = cli_title
        fields["intro"] = cli_intro or cli_title
        return normalize_fields(fields), "CLI --file/--title"

    # 2) 配置文件
    cfg = _load(config_path or _default_config_path())
    if cfg:
        date_key = override_date or today_str()
        base = dict(DEFAULT_FIXED)
        if cfg.get("fixed"):
            base.update({k: v for k, v in cfg["fixed"].items() if not k.startswith("_")})

        # 2a) 按日期匹配当天
        for it in (cfg.get("resources") or []):
            if it.get("date") == date_key:
                fields = dict(base)
                for k, v in it.items():
                    if k == "date" or k.startswith("_"):
                        continue
                    fields[k] = v
                if not fields.get("intro"):
                    fields["intro"] = fields.get("title", "")
                return normalize_fields(fields), f"config[{date_key}]"

        # 2b) default 兜底
        d = cfg.get("default")
        if d and d.get("file") and d.get("title"):
            fields = dict(base)
            for k, v in d.items():
                if k.startswith("_"):
                    continue
                fields[k] = v
            if not fields.get("intro"):
                fields["intro"] = fields.get("title", "")
            return normalize_fields(fields), "config default"

    raise SystemExit(
        "未找到资源配置: 请传入 --file/--title, "
        "或在配置文件中提供当天(date=%s)或 default 资源" % (override_date or today_str())
    )


def make_resource_title(stem):
    """把拆页/整本 PDF 文件名 stem 转成可读资源标题。

    2026-07-23_1904_Auerbach_Otto_P005 -> 曲目《Auerbach Otto》 5
    2026-07-23_1904_Auerbach_Otto       -> 曲目《Auerbach Otto》

    规则: 仅当 stem 以 日期前缀(YYYY-MM-DD_) 开头才转换; 否则原样返回(避免误伤非曲目资源)。
    去掉开头 日期 + 纯数字时间 前缀段; 中段(作者, 下划线转空格)放《》; 末段 P005 去掉 P 与
    前导零得页码。无法解析时回退原 stem。
    """
    if not re.match(r"^\d{4}-\d{2}-\d{2}_", stem):
        return stem
    parts = stem.split("_")
    # 去掉开头 日期(2026-07-23) 与 纯数字时间(1904) 前缀段
    while parts and (re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]) or re.match(r"^\d+$", parts[0])):
        parts.pop(0)
    if not parts:
        return stem
    # 末段 P005 -> 页码(去 P 与前导零)
    page = None
    if re.match(r"^P0*\d+$", parts[-1]):
        page = str(int(parts[-1][1:]))
        parts.pop()
    if not parts:
        return stem
    author = " ".join(parts)
    return f"曲目《{author}》 {page}" if page else f"曲目《{author}》"


def resolve_pdf_asset(pdf_path, title=None, intro=None):
    """assets/ 下已预处理改名(日期_原文件名)的 PDF 专用: parentId=综合资源,
    title/intro 默认由文件名 stem 解析为可读标题(如 曲目《Auerbach Otto》 5)。

    供 publish_resource_api.py / publish_resource_playwright.py 在「传入 assets/ 下 .pdf」
    或「批量上传当天日期前缀文件」时调用, 替代 resolve_resource()。
    文件名已由 rename_assets.py 预处理为 日期_原文件名.ext, 故此处不再拼接日期。
    """
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    fields = dict(DEFAULT_FIXED)
    fields["parentId"] = "综合资源"    # normalize 翻成真实 value 并同步 rtype
    fields["file"] = pdf_path
    fields["title"] = title or make_resource_title(stem)
    fields["intro"] = intro or fields["title"]
    return normalize_fields(fields), f"pdf-asset {stem}"
