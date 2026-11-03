#!/usr/bin/env bash
# 停止动作库网页服务
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$DIR/server.pid"
if [ ! -f "$PIDFILE" ]; then
  echo "没有 PID 文件，服务可能未启动"
  exit 0
fi
PID="$(cat "$PIDFILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  for i in $(seq 1 20); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.2
  done
  kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null
  echo "已停止 PID $PID"
else
  echo "进程 $PID 已不在"
fi
rm -f "$PIDFILE"
