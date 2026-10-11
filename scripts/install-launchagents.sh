#!/bin/sh
set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
uv=$(command -v uv) || { echo "uv not found on PATH" >&2; exit 1; }
browser=$(command -v agent-browser) || { echo "agent-browser not found on PATH" >&2; exit 1; }
path="$(dirname "$uv"):$(dirname "$browser"):/usr/bin:/bin:/usr/sbin:/sbin"
logs="$HOME/.config/context-mcp"
agents="$HOME/Library/LaunchAgents"
mkdir -p "$logs" "$agents"

install_agent() {
    label="com.context-mcp.$1"
    plist="$agents/$label.plist"
    cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>
        <string>$uv</string>
        <string>run</string>
        <string>--frozen</string>
        <string>--directory</string>
        <string>$repo</string>
        <string>python</string>
        <string>-m</string>
        <string>$2</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$path</string>
    </dict>
    <key>StartInterval</key>
    <integer>28800</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>LowPriorityIO</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$logs/$1.err</string>
    <key>StandardErrorPath</key>
    <string>$logs/$1.err</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$plist"
    echo "loaded $label"
}

install_agent outlook-refresh context_mcp.mail.refresh
install_agent imperial-refresh context_mcp.imperial.refresh
