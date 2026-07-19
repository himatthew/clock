#!/usr/bin/env bash
# 之江汇教育广场 每日自动发布 (陈晓雯名师工作室 sid=2174, 账号 洪彦)
# 步骤:
#   1) playwright(cube 云管理台登录)刷新 cookies.txt, 拿到 ck_ms + eduyun_sessionid
#   2) 发布当天话题 + 旧话题撤顶取消加精 + 新话题置顶加精
#   3) 参与最新一个未加入教研活动 + 提问研讨留 5 条言
#   4) 微信推送(PushPlus, 四态汇总; 成败都推)
# 注意: 资源上传已由独立的 split_upload_daily.sh (每天 07:30) 负责「拆页批量上传」, 此处不再上传。
# 由 crontab 每天 07:00 (Asia/Shanghai) 调用: 0 7 * * * bash /home/ubuntu/clock/run_daily.sh
# (自 2026-07-19 起生效, 见下方 START_DATE 守卫)
set -uo pipefail

export TZ=Asia/Shanghai
APP=/home/ubuntu/clock
VENV=/home/ubuntu/venv_clock
PY="$VENV/bin/python"
LOG="$APP/cron.log"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*"; }

cd "$APP" || { echo "[$(ts)] ERROR: cd $APP 失败"; exit 1; }

# 确保 cookie 有效: 失效才刷新(避免频繁刷新触发账号风控)。
# 默认基础检测(ck_ms 登录态); 传 --strict 时额外检测文章发布页权限。
ensure_cookie() {
    local strict_flag="${1:-}"
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
}

# 启动日守卫: 未到 START_DATE 前不执行(避免部署当天提前触发)
START_DATE=2026-07-19
TODAY_DATE="$(date '+%Y-%m-%d')"
if [[ "$TODAY_DATE" < "$START_DATE" ]]; then
    log "未到启动日 $START_DATE (今天 $TODAY_DATE), 跳过本次执行"
    exit 0
fi

log "=== 每日任务开始 ==="

# 1) 确保 cookie 有效(失效才刷新)
log "[1/4] 确保 cookie 有效(失效才刷新) ..."
ensure_cookie ""
CK_EXIT=$?
log "      cookie exit=$CK_EXIT"

# 2) 发布当天话题 + 旧话题撤顶取消加精 + 新话题置顶加精
log "[2/4] 发布话题+置顶加精 (publish_topic_manager.py) ..."
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    "$PY" src/publish_topic_manager.py >> "$LOG" 2>&1
TK_EXIT=$?
log "      话题完成 exit=$TK_EXIT"

# 3) 教研参与 + 留言 (playwright: 参与最新一个未加入活动 + 留 5 条言)
log "[3/4] 教研参与+留言 (join_activity_and_comment.py) ..."
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    "$PY" src/join_activity_and_comment.py >> "$LOG" 2>&1
AC_EXIT=$?
log "      教研完成 exit=$AC_EXIT"

# 4) 微信推送结果 (PushPlus; 资源上传改由独立拆页任务上报, 此处 --no-resource)
COOKIE_STATUS="成功";   [ "$CK_EXIT" -ne 0 ] && COOKIE_STATUS="失败 (exit=$CK_EXIT)"
TOPIC_STATUS="成功";    [ "$TK_EXIT" -ne 0 ] && TOPIC_STATUS="失败 (exit=$TK_EXIT)"
ACTIVITY_STATUS="成功"; [ "$AC_EXIT" -ne 0 ] && ACTIVITY_STATUS="失败 (exit=$AC_EXIT)"

DETAIL="$(tail -n 25 "$LOG")"
log "[4/4] 推送微信通知 (notify.py --no-resource --no-article) ..."
"$PY" src/notify.py \
    --date "$TODAY_DATE" \
    --cookie-status "$COOKIE_STATUS" \
    --topic-status "$TOPIC_STATUS" \
    --activity-status "$ACTIVITY_STATUS" \
    --no-resource \
    --no-article \
    --detail "$DETAIL" >> "$LOG" 2>&1
log "      推送完成 exit=$?"

log "=== 每日任务结束 ==="
