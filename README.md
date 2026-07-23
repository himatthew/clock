# 之江汇教育广场 · 自动发布工具

名师工作室（sid=2174）的**话题发布**与**资源课件上传**自动化。
4 个脚本 = 话题/资源 × 接口版/Playwright 版，全部由外部配置文件驱动。

## 目录结构

```
.
├── publish_topic_api.py          话题 · 接口直发（最快，推荐）
├── publish_topic_playwright.py   话题 · Playwright（可视化排查用）
├── publish_resource_api.py       资源 · 接口直发（OSS 直传，推荐）
├── publish_resource_playwright.py资源 · Playwright（--mode auto/whitebox）
├── topic_config.py               话题配置加载器（被两个话题脚本复用）
├── resource_config.py            资源配置加载器（被两个资源脚本复用）
├── topics_config.json            话题排期（按日期）
├── resources_config.json         资源排期 + 工作室固定字段（fixed 段）
├── cookies.txt                   登录态 Cookie（切勿外泄/提交）
├── requirements.txt
├── _archive/                     历史调试脚本（归档，可回查）
└── .workbuddy/memory/            项目记忆（MEMORY.md + 每日日志）
```

## 快速开始

```bash
# 话题：发配置里「今天」的那条
python3 publish_topic_api.py cookies.txt

# 资源：发配置里「今天」的那条（自动生成新 MD5 变体绕去重）
python3 publish_resource_api.py cookies.txt
```

## Cookie 刷新（refresh_cookie.py）

登录态过期时，自动重新登录并覆盖 `cookies.txt`（覆盖前自动备份）。
默认走「我是教师」落到**名师工作室（ms.zjer.cn）**，刷新出的 Cookie 含发布必需的 `ck_ms`，直接供话题/资源脚本使用。
凭据支持两种方式，脚本都会读取：①环境变量 `ZJER_USER`/`ZJER_PASS`；②工作区 `.env` 文件（脚本自动载入，不覆盖已存在的真实环境变量）。

```bash
# 方式A: 环境变量(适合 CI / 一次性)
ZJER_USER=你的账号 ZJER_PASS='你的密码' python3 refresh_cookie.py

# 方式B: 已写好 .env 后直接跑(免传参)
python3 refresh_cookie.py

# 纯 API 模式（更快，若该站可行）
python3 refresh_cookie.py --mode api

# 调试：弹出真实浏览器看登录过程
python3 refresh_cookie.py --no-headless
```

> ⚠️ `.env` 含明文密码、`cookies.txt` 含登录态，均已加入 `.gitignore`，**切勿提交/外泄**。

- 登录/校验失败不会覆盖旧 Cookie；旧文件会先备份为 `cookies.txt.<时间戳>.bak`。
- 刷新后可用 `python3 publish_topic_api.py cookies.txt --dry-run` 快速验证。

## 配置文件格式

`topics_config.json` / `resources_config.json` 均支持三种写法：

```jsonc
{
  "fixed": {                 // 仅资源有：工作室固定字段，可覆盖默认值
    "classid": "22", "subject": "jcsub20", "parentId": "db1a...",
    "editionid": "ms_other_330000", "original": "0", "original_author": "洪彦"
  },
  "default": { "title": "...", "content": "...", "file": "..." },  // 兜底
  "resources": [             // 或 topics: 按 date 排期
    { "date": "2026-07-14", "title": "...", "content": "...", "file": "..." }
  ]
}
```

每天只需往 `resources[]` / `topics[]` 加一条 `date` 匹配当天的条目即可。

## 常用参数（四个脚本通用）

| 参数 | 作用 |
|---|---|
| `--date YYYY-MM-DD` | 取指定日期的条目（补发/测试） |
| `--list` | 列出配置里全部条目后退出 |
| `--config <file>` | 指定配置文件（默认脚本同目录的 topics/resources_config.json） |
| `--dry-run` | （接口版）停在提交前，预览数据 |
| `--mode whitebox` | （Playwright 资源版）弹窗填到发布前，手动点【发布】 |
| `--no-variant` | （Playwright 资源版）用原文件不改 MD5 |

CLI 直接传 `--title`/`--file` 优先级最高，会越过配置。

## 关键注意

- **去重按文件 MD5**：脚本每次自动复制源文件追加 16 字节随机数据，强制拿新 fid 绕过。
- **资源接口版成功判据**：提交响应 `type=1` 上传资源成功；`type=2` 被去重拦截。
- **资源列表页是 AJAX 懒加载**：后台看不到刚传的资源，以提交响应 `type` 为准，前台稍候刷新。
- 运行环境用 managed venv：`/Users/matthew/.workbuddy/binaries/python/envs/default/bin/python`
