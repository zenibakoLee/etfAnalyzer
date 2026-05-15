#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

mkdir -p "$LAUNCH_AGENTS"

SERVICES=(
    "com.etfanalyzer.bot"
)

echo "=== ETF Analyzer launchd 설치 ==="

for svc in "${SERVICES[@]}"; do
    plist="$SCRIPT_DIR/${svc}.plist"
    target="$LAUNCH_AGENTS/${svc}.plist"

    if launchctl list 2>/dev/null | grep -q "$svc"; then
        echo "[$svc] 기존 서비스 중지..."
        launchctl bootout "gui/$(id -u)/$svc" 2>/dev/null || true
    fi

    if [ -L "$target" ] || [ -f "$target" ]; then
        rm -f "$target"
    fi

    ln -s "$plist" "$target"
    launchctl bootstrap "gui/$(id -u)" "$target"
    echo "[$svc] 등록 완료"
done

echo ""
echo "=== 설치 완료 ==="
echo "상태 확인: launchctl list | grep etfanalyzer"
echo "로그 확인: tail -f ~/dev/etfAnalyzer/logs/*.log"
