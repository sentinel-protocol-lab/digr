#!/bin/bash
# Digr — Mac Installer
# Double-click this file to install.
# If macOS blocks it on first run: right-click → Open → Open (web downloads only).

cd "$(dirname "$0")"

set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step()  { echo -e "\n${CYAN}>> $1${NC}"; }
ok()    { echo -e "   ${GREEN}OK${NC}  $1"; }
warn()  { echo -e "   ${YELLOW}!!${NC}  $1"; }
fail()  { echo -e "   ${RED}X${NC}   $1"; echo ""; read -p "Press Enter to exit..."; exit 1; }

echo ""
echo "  Digr — Installer"
echo "  ====================================="
echo ""

# ── 1. Install uv if missing ──────────────────────────────────────────────────
step "Checking for uv..."

UV_PATH=""
for candidate in \
    "$HOME/.local/bin/uv" \
    "/opt/homebrew/bin/uv" \
    "/usr/local/bin/uv"; do
    if [ -x "$candidate" ]; then
        UV_PATH="$candidate"
        break
    fi
done

if [ -z "$UV_PATH" ]; then
    warn "uv not found. Installing now (requires internet)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    UV_PATH=$(command -v uv 2>/dev/null)
    if [ -z "$UV_PATH" ]; then
        fail "uv installed but could not be located. Re-run this script."
    fi
fi
ok "Found uv: $UV_PATH"

# ── 2. Find and extract the .mcpb bundle ─────────────────────────────────────
step "Locating .mcpb bundle..."

MCPB=$(ls "$(dirname "$0")"/*.mcpb 2>/dev/null | head -1)
if [ -z "$MCPB" ]; then
    fail "No .mcpb file found next to this installer. Keep them in the same folder."
fi
ok "Found bundle: $(basename "$MCPB")"

INSTALL_DIR="$HOME/Library/Application Support/Digr"
step "Installing to: $INSTALL_DIR"

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
unzip -qo "$MCPB" -d "$INSTALL_DIR" || fail "Failed to extract bundle."
ok "Bundle extracted."

# ── 3. Locate Claude Desktop config ──────────────────────────────────────────
step "Locating Claude Desktop..."

CONFIG_DIR="$HOME/Library/Application Support/Claude"
CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

if [ ! -d "$CONFIG_DIR" ]; then
    fail "Claude Desktop not found. Install it from https://claude.ai/download"
fi
ok "Found Claude Desktop config."

# ── 4. Patch config JSON ──────────────────────────────────────────────────────
step "Registering server..."

[ -f "$CONFIG_FILE" ] || echo '{}' > "$CONFIG_FILE"

# Validate JSON (osascript -l JavaScript is built into macOS — no python3 needed)
if ! osascript -l JavaScript -e "JSON.parse($.NSString.alloc.initWithDataEncoding($.NSData.dataWithContentsOfFile('$CONFIG_FILE'), $.NSUTF8StringEncoding).js)" &>/dev/null; then
    fail "claude_desktop_config.json is malformed. Fix it manually: $CONFIG_FILE"
fi

cp "$CONFIG_FILE" "$CONFIG_FILE.bak"

# Patch config JSON using JavaScript for Automation (JXA)
osascript -l JavaScript <<EOF
var fm = $.NSFileManager.defaultManager;
var data = $.NSData.dataWithContentsOfFile("$CONFIG_FILE");
var raw = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js;
var config = JSON.parse(raw);

if (!config.mcpServers) config.mcpServers = {};
config.mcpServers["digr"] = {
    command: "$UV_PATH",
    args: ["run", "--directory", "$INSTALL_DIR", "--extra", "audio", "digr"]
};

var out = JSON.stringify(config, null, 2);
var str = $.NSString.alloc.initWithUTF8String(out);
str.writeToFileAtomicallyEncodingError("$CONFIG_FILE", true, $.NSUTF8StringEncoding, null);
EOF

ok "Config written."

# ── 5. Restart Claude Desktop ─────────────────────────────────────────────────
step "Restarting Claude Desktop..."

if pgrep -x "Claude" &>/dev/null; then
    osascript -e 'quit app "Claude"' 2>/dev/null || pkill -x "Claude" || true
    sleep 2
    ok "Claude Desktop stopped."
fi

if [ -d "/Applications/Claude.app" ]; then
    open "/Applications/Claude.app"
    ok "Claude Desktop restarted."
else
    warn "Could not find Claude.app — please open it manually."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ====================================="
echo -e "  ${GREEN}Installation complete!${NC}"
echo ""
echo "  Digr is now available in Claude Desktop."
echo "  The first launch downloads audio libraries (~1 min). After that it's instant."
echo ""
read -p "Press Enter to close..."
