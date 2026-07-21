#!/usr/bin/env bash
# 之江汇教育广场 · 每日发布「当日文章」到教师文章栏目 (独立 cron)
# 流程: (cookie 较新则跳过刷新) -> 读 docs/articles/<今天>_*.md -> 填表提交 -> 微信提醒
# 由 crontab 每天 07:00 与另两任务并行启动: 0 7 * * * bash /home/ubuntu/clock/publish_article_daily.sh
# (自 2026-07-19 起生效, 见下方 START_DATE 守卫)
set -uo pipefail

export TZ=Asia/Shanghai
APP=/home/ubuntu/clock
VENV=/home/ubuntu/venv_clock
PY="$VENV/bin/python"
LOG="$APP/article_cron.log"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

cd "$APP" || { echo "[$(ts)] ERROR: cd $APP 失败"; exit 1; }

# 并发安全: 三任务并行启动时, 若 cookie 同时过期会并发刷新并互相覆盖 cookies.txt。
# 用 flock 把「检测+刷新」整体串行化(第一个抢到锁的刷新, 其余等待后复检即跳过)。
COOKIE_LOCK="$APP/.cookie_lock"
ensure_cookie() {
    local strict_flag="${1:-}"
    (
        flock -w 180 9 || { log "[cookie] 获取锁失败, 跳过刷新"; return 0; }
        log "[cookie] 检测有效性 (refresh_cookie.py --check $strict_flag) ..."
        if env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
            "$PY" src/refresh_cookie.py --check $strict_flag >> "$LOG" 2>&1; then
            log "[cookie] 仍有效, 跳过刷新"
            return 0
        fi
        log "[cookie] 失效, 执行刷新 (--mode playwright) ..."
        env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
            "$PY" src/refresh_cookie.py --mode playwright >> "$LOG" 2>&1
        return $?
    ) 9>"$COOKIE_LOCK"
}

# 启动日守卫: 未到 START_DATE 前不执行(文章库自 2026-07-19 起)
START_DATE=2026-07-19
TODAY_DATE="$(date '+%Y-%m-%d')"
if [[ "$TODAY_DATE" < "$START_DATE" ]]; then
    log "未到启动日 $START_DATE (今天 $TODAY_DATE), 跳过本次执行"
    exit 0
fi

log "=== 文章发布任务开始 ==="

# 0) 确保 cookie 有效(失效才刷新)
#    文章发布页(add)需 eduyun_sessionid 管理会话(短命), 仅 ck_ms 会被判无权限,
#    故用 --strict 额外检测文章发布权限; 仍有效则复用, 失效才刷新(每天最多 1 次)。
log "[0/2] 确保 cookie 有效(失效才刷新, --strict) ..."
ensure_cookie "--strict"
CK_EXIT=$?
log "      cookie exit=$CK_EXIT"

# 1) 发布当日文章
log "[1/2] 发布当日文章 (publish_article_playwright.py) ..."
"$PY" src/publish_article_playwright.py cookies.txt >> "$LOG" 2>&1
ART_EXIT=$?
log "      发布完成 exit=$ART_EXIT"

# 2) 微信推送结果 (PushPlus; 仅显示 工作室/Cookie/文章)
COOKIE_STATUS="成功"; [ "$CK_EXIT" -ne 0 ] && COOKIE_STATUS="失败 (exit=$CK_EXIT)"
if [ "$ART_EXIT" -eq 0 ]; then
    ART_STATUS="成功"
    HEADLINE="成功！毛毛小主！当日文章已发布成功"
else
    ART_STATUS="失败 (exit=$ART_EXIT)"
    HEADLINE="失败～毛毛小主 文章发布失败"
fi

# 2.1) 从日志提取「本次运行」每篇文章的标题+状态(两篇), 上送通知显式列出。
#     注意: 日志持续追加且从不截断, 若直接全文件 grep 会把历史日期的 1|OK|... 也捞进来,
#     导致通知误列旧文章(逐日累积成 4/6/10 篇)。故限定在最后一个运行起始标记之后。
START_LINE="$(grep -n '=== 文章发布任务开始 ===' "$LOG" | tail -1 | cut -d: -f1)"
ARTS="$(tail -n "+${START_LINE:-1}" "$LOG" | grep -aE '^[0-9]+\|(OK|FAIL)\|' | tail -n 10)"
ARTICLES_ARG=""
if [ -n "$ARTS" ]; then
    while IFS='|' read -r idx st title; do
        [ "$st" = "OK" ] && stzh="成功" || stzh="失败"
        if [ -z "$ARTICLES_ARG" ]; then
            ARTICLES_ARG="$title:$stzh"
        else
            ARTICLES_ARG="$ARTICLES_ARG;$title:$stzh"
        fi
    done <<< "$ARTS"
fi
log "      [文章结果] $ARTICLES_ARG"

DETAIL="$(tail -n 25 "$LOG")"
log "[2/2] 推送微信通知 (notify.py --article-status --articles) ..."
"$PY" src/notify.py \
    --date "$TODAY_DATE" \
    --cookie-status "$COOKIE_STATUS" \
    --article-status "$ART_STATUS" \
    --articles "$ARTICLES_ARG" \
    --no-resource --no-topic --no-activity \
    --headline "$HEADLINE" \
    --title "$HEADLINE" \
    --detail "$DETAIL" >> "$LOG" 2>&1
log "      推送完成 exit=$?"

log "=== 文章发布任务结束 ==="
