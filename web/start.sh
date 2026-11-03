#!/usr/bin/env bash
# 启动动作库网页服务（端口 8099）
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$DIR/server.pid"
LOGFILE="$DIR/logs/server.log"
PORT="${ACLIB_PORT:-8099}"
mkdir -p "$DIR/logs"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "已在运行，PID $(cat "$PIDFILE") —— http://0.0.0.0:$PORT"
  exit 0
fi

if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "端口 $PORT 已被其他进程占用，先确认是谁："
  ss -ltnp 2>/dev/null | grep ":$PORT " || true
  exit 1
fi

cd "$DIR"
nohup python3.14 server.py >> "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

for i in $(seq 1 30); do
  if curl -s -o /dev/null -m 1 "http://127.0.0.1:$PORT/api/health"; then
    echo "已启动 PID $(cat "$PIDFILE") —— http://127.0.0.1:$PORT  (日志 $LOGFILE)"
    exit 0
  fi
  sleep 0.3
done
echo "启动超时，看日志：$LOGFILE"
tail -20 "$LOGFILE"
exit 1
