# Digr v1.0.0 - Windows Installer
# Right-click this file -> "Run with PowerShell"
# Or use install.bat to bypass execution policy.

$ErrorActionPreference = "Stop"
$MIN_PYTHON = "3.11"
$MAX_PYTHON = "3.13"

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "   OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "   !!  $msg" -ForegroundColor Yellow }
function Write-Fail($msg) {
    Write-Host "   X   $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "  Digr v1.0.0 - Installer" -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor DarkGray
Write-Host ""

# ── 1. Install uv if missing ──────────────────────────────────────────────────
Write-Step "Checking for uv..."

$uvPath = $null
$candidates = @(
    "$env:LOCALAPPDATA\uv\bin\uv.exe",
    "$env:USERPROFILE\.local\bin\uv.exe",
    "$env:USERPROFILE\.cargo\bin\uv.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $uvPath = $c; break }
}

if (-not $uvPath) {
    Write-Warn "uv not found. Installing now (requires internet)..."
    try {
        $installScript = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
        Invoke-Expression $installScript
        # Refresh PATH for this session
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","User") + ";" + $env:PATH
        foreach ($c in $candidates) {
            if (Test-Path $c) { $uvPath = $c; break }
        }
        if (-not $uvPath) { Write-Fail "uv installed but could not be located. Re-run this script." }
    } catch {
        Write-Fail "Could not install uv. Visit: https://docs.astral.sh/uv/getting-started/installation/"
    }
}
Write-OK "Found uv: $uvPath"

# ── 2. Verify Python version ──────────────────────────────────────────────────
Write-Step "Checking Python version..."

# Pre-compute version bounds for comparison (needed by fallback block below)
$minParts = $MIN_PYTHON.Split(".") | ForEach-Object { [int]$_ }
$maxParts = $MAX_PYTHON.Split(".") | ForEach-Object { [int]$_ }
$minNum = $minParts[0] * 100 + $minParts[1]
$maxNum = $maxParts[0] * 100 + $maxParts[1]

$pyVersion = $null
try {
    $pyOutput = & $uvPath python --version 2>&1
    if ($pyOutput -match "Python (\d+\.\d+)") {
        $pyVersion = $Matches[1]
    }
} catch {}

if (-not $pyVersion) {
    # uv can manage Python itself - try to install a compatible version
    Write-Warn "No Python found. Asking uv to install Python $MIN_PYTHON..."
    try {
        $installOutput = & $uvPath python install $MIN_PYTHON 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "uv python install output: $installOutput"
        }
        $pyOutput = & $uvPath python --version 2>&1
        if ($pyOutput -match "Python (\d+\.\d+)") {
            $pyVersion = $Matches[1]
        }
    } catch {
        Write-Warn "uv python install failed: $_"
    }
}

# Fallback: check system Python via py launcher or PATH
if (-not $pyVersion) {
    Write-Warn "Trying system Python..."
    foreach ($cmd in @("py", "python3", "python")) {
        try {
            $testExe = (Get-Command $cmd -ErrorAction SilentlyContinue).Source
            if ($testExe) {
                $testOutput = & $testExe --version 2>&1
                if ($testOutput -match "Python (\d+)\.(\d+)") {
                    $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                    if (($maj * 100 + $min) -ge ($minParts[0] * 100 + $minParts[1])) {
                        $pyVersion = "$maj.$min"
                        Write-OK "Found system Python: $testExe ($testOutput)"
                        break
                    }
                }
            }
        } catch {}
    }
}

if (-not $pyVersion) {
    Write-Fail "Could not find or install Python >= $MIN_PYTHON. Install Python from https://python.org"
}

# Compare version numbers
$pyParts = $pyVersion.Split(".") | ForEach-Object { [int]$_ }
$pyNum  = $pyParts[0] * 100 + $pyParts[1]

if ($pyNum -lt $minNum) {
    Write-Fail "Python $pyVersion is too old. Requires >= $MIN_PYTHON. Install from https://python.org"
}
if ($pyNum -gt $maxNum) {
    Write-Warn "Python $pyVersion is newer than tested ($MAX_PYTHON). It may work but is not officially supported."
}

Write-OK "Python $pyVersion"

# ── 3. Find and extract the .mcpb bundle ───────────────────────────────────────
Write-Step "Locating .mcpb bundle..."

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$mcpb = Get-ChildItem -Path $scriptDir -Filter "*.mcpb" | Select-Object -First 1
if (-not $mcpb) {
    Write-Fail "No .mcpb file found next to this installer. Keep them in the same folder."
}
Write-OK "Found bundle: $($mcpb.Name)"

$installDir = Join-Path $env:LOCALAPPDATA "Digr"
Write-Step "Installing to: $installDir"

if (Test-Path $installDir) { Remove-Item $installDir -Recurse -Force }
New-Item -ItemType Directory -Path $installDir | Out-Null

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($mcpb.FullName, $installDir)
Write-OK "Bundle extracted."

# ── 4. Locate Claude Desktop config ───────────────────────────────────────────
Write-Step "Locating Claude Desktop..."

# Claude Desktop stores its config in one of two places, depending on how the
# build was packaged:
#   - Classic installer:  %APPDATA%\Claude
#   - MSIX package (current website + Microsoft Store builds): Windows redirects
#     the app's Roaming folder into a per-package sandbox at
#     %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude
# Probe both (legacy first) and use whichever actually exists. This is OS-version
# agnostic: the MSIX redirection works identically on Windows 10 and 11.
$configDir = $null

$classicDir = Join-Path $env:APPDATA "Claude"
if (Test-Path $classicDir) {
    $configDir = $classicDir
} else {
    $packagesRoot = Join-Path $env:LOCALAPPDATA "Packages"
    if (Test-Path $packagesRoot) {
        $configDir = Get-ChildItem -Path $packagesRoot -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "LocalCache\Roaming\Claude" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
    }
}

if (-not $configDir) {
    Write-Fail "Claude Desktop config folder not found. Install Claude Desktop from https://claude.ai/download, then OPEN it and sign in once (that first launch creates the folder), and re-run this installer."
}

$configFile = Join-Path $configDir "claude_desktop_config.json"
Write-OK "Found Claude Desktop config: $configDir"

# ── 5. Patch config JSON ──────────────────────────────────────────────────────
Write-Step "Registering server..."

# Write UTF-8 *without* a BOM. Windows PowerShell's `Set-Content -Encoding UTF8`
# prepends a BOM, which can break strict JSON parsers reading the config.
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

if (-not (Test-Path $configFile)) {
    [System.IO.File]::WriteAllText($configFile, '{}', $utf8NoBom)
}

$raw = Get-Content $configFile -Raw -Encoding UTF8
try {
    # NB: ConvertFrom-Json has no -Depth in Windows PowerShell 5.1 (the
    # powershell.exe that install.bat invokes on Windows 10). Its default depth
    # is more than enough for this config, so don't pass -Depth here.
    $config = $raw | ConvertFrom-Json
} catch {
    Write-Fail "claude_desktop_config.json is malformed. Fix it manually: $configFile"
}

# Backup
Copy-Item $configFile "$configFile.bak" -Force
Write-OK "Backup saved."

if (-not $config.PSObject.Properties["mcpServers"]) {
    $config | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value ([PSCustomObject]@{})
}

$serverEntry = [PSCustomObject]@{
    command = $uvPath
    args    = @("run", "--directory", $installDir, "--extra", "audio", "digr")
}

if ($config.mcpServers.PSObject.Properties["digr"]) {
    $config.mcpServers."digr" = $serverEntry
} else {
    $config.mcpServers | Add-Member -MemberType NoteProperty -Name "digr" -Value $serverEntry
}

$json = $config | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($configFile, $json, $utf8NoBom)
Write-OK "Config written."

# ── 6. Restart Claude Desktop ─────────────────────────────────────────────────
Write-Step "Restarting Claude Desktop..."

$claude = Get-Process -Name "Claude" -ErrorAction SilentlyContinue
if ($claude) {
    Stop-Process -Name "Claude" -Force
    Start-Sleep -Seconds 2
    Write-OK "Claude Desktop stopped."
}

# Relaunch automatically. Classic builds have a fixed exe path; MSIX builds are
# launched through the Apps folder via their package family name.
$relaunched = $false
$claudeExe = Join-Path $env:LOCALAPPDATA "AnthropicClaude\claude.exe"
if (Test-Path $claudeExe) {
    Start-Process $claudeExe
    $relaunched = $true
} else {
    try {
        $pkg = Get-AppxPackage -Name "Claude" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pkg) {
            Start-Process "shell:AppsFolder\$($pkg.PackageFamilyName)!Claude"
            $relaunched = $true
        }
    } catch {}
}
if ($relaunched) {
    Write-OK "Claude Desktop restarted."
} else {
    Write-Warn "Please open Claude Desktop manually to load Digr."
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkGray
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Digr is now available in Claude Desktop." -ForegroundColor White
Write-Host "  The first launch downloads audio libraries (~1 min). After that it's instant." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  15 tools available (10 free, 5 Pro)" -ForegroundColor DarkGray
Write-Host "  Pro features: set license key in %APPDATA%\digr\license.key" -ForegroundColor DarkGray
Write-Host ""
Read-Host "Press Enter to close"
