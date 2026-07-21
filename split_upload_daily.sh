#!/usr/bin/env bash
# 之江汇教育广场 · 资源「拆页批量上传」每日任务 (独立 cron)
# 流程: (cookie 较新则跳过刷新) -> 拆当日 PDF 为单页 -> 逐页上传 -> 微信提醒
# 由 crontab 每天 07:00 与另两任务并行启动: 0 7 * * * bash /home/ubuntu/clock/split_upload_daily.sh
# (自 2026-07-19 起生效, 见下方 START_DATE 守卫)
set -uo pipefail

export TZ=Asia/Shanghai
APP=/home/ubuntu/clock
VENV=/home/ubuntu/venv_clock
PY="$VENV/bin/python"
LOG="$APP/split_cron.log"

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

# 启动日守卫: 未到 START_DATE 前不执行
START_DATE=2026-07-19
TODAY_DATE="$(date '+%Y-%m-%d')"
if [[ "$TODAY_DATE" < "$START_DATE" ]]; then
    log "未到启动日 $START_DATE (今天 $TODAY_DATE), 跳过本次执行"
    exit 0
fi

log "=== 拆页上传任务开始 ==="

# 0) 确保 cookie 有效(失效才刷新): 资源上传页需 eduyun_sessionid 新鲜会话, 用 --strict 守卫
log "[0/2] 确保 cookie 有效(失效才刷新, --strict) ..."
ensure_cookie "--strict"
CK_EXIT=$?
log "      cookie exit=$CK_EXIT"

# 1) 拆页 + 批量上传 + 微信提醒
log "[1/2] 拆页批量上传 (split_upload_daily.py) ..."
"$PY" src/split_upload_daily.py --cookie cookies.txt >> "$LOG" 2>&1
UP_EXIT=$?
log "      上传完成 exit=$UP_EXIT"

log "=== 拆页上传任务结束 ==="
