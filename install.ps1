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

# (1) Prefer a Python that already exists on this machine. uv automatically
# discovers and reuses system Pythons for `uv sync`/`uv run`, so when one is
# present we skip uv's managed download entirely. Probe the usual launchers.
foreach ($cmd in @("py", "python3", "python")) {
    try {
        $testExe = (Get-Command $cmd -ErrorAction SilentlyContinue).Source
        if ($testExe) {
            $testOutput = & $testExe --version 2>&1
            if ($testOutput -match "Python (\d+)\.(\d+)") {
                $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                if (($maj * 100 + $min) -ge $minNum) {
                    $pyVersion = "$maj.$min"
                    Write-OK "Found Python: $testExe ($testOutput)"
                    break
                }
            }
        }
    } catch {}
}

# (2) No usable system Python -> have uv download a managed one. uv writes its
# progress ("Downloading cpython... (24.5MiB)") to stderr; under the script-wide
# $ErrorActionPreference='Stop' that first line was promoted to a terminating
# error and misreported as "uv python install failed" -- the download wasn't
# actually failing. Drop to 'Continue' so stderr is just text, judge success by
# the real exit code, and retry once for a genuinely interrupted download.
if (-not $pyVersion) {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    for ($attempt = 1; ($attempt -le 2) -and (-not $pyVersion); $attempt++) {
        Write-Warn "No system Python found. Downloading Python $MIN_PYTHON (attempt $attempt of 2)..."
        & $uvPath python install $MIN_PYTHON 2>&1 |
            ForEach-Object { Write-Host "   $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -eq 0) {
            $pyVersion = $MIN_PYTHON
            Write-OK "Downloaded Python $MIN_PYTHON"
        } elseif ($attempt -lt 2) {
            Write-Warn "Download did not complete; retrying..."
        }
    }
    $ErrorActionPreference = $prevEAP
}

if (-not $pyVersion) {
    Write-Fail "Could not find or download Python >= $MIN_PYTHON. Install Python from https://python.org (tick 'Add python.exe to PATH' during setup), or run 'winget install Python.Python.3.13', then re-run this installer."
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

# Wipe any previous install so we lay down a clean copy. On Windows a loaded
# .pyd/DLL can't be deleted while a process holds it open -- so if an older Digr
# is already installed, Claude Desktop (running in the tray) keeps its compiled
# dependencies locked and Remove-Item dies with "Access to the path is denied".
# (macOS/Linux don't hit this -- unlinking an open file is allowed there.) So:
# stop Claude first (we relaunch it at the end anyway), then remove with a short
# retry for any straggling uv/python child process, and on a surviving lock give
# an actionable message instead of dying on the raw PowerShell error.
if (Test-Path $installDir) {
    if (Get-Process -Name "Claude" -ErrorAction SilentlyContinue) {
        Write-Warn "Closing Claude Desktop to free the previous install..."
        Stop-Process -Name "Claude" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    $removed = $false
    foreach ($attempt in 1..3) {
        try {
            Remove-Item $installDir -Recurse -Force -ErrorAction Stop
            $removed = $true
            break
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $removed) {
        Write-Fail "Could not replace the existing install at '$installDir' -- a file is still in use. Fully quit Claude Desktop (right-click its icon in the system tray near the clock, then Quit), close anything else using Digr, and run this installer again. If it still fails, restart Windows and re-run."
    }
}
New-Item -ItemType Directory -Path $installDir | Out-Null

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($mcpb.FullName, $installDir)
Write-OK "Bundle extracted."

# ── 3b. Pre-build the dependency environment ───────────────────────────────────
Write-Step "Building Digr's environment (downloads ~60 MB, 1-2 min)..."

# Build the .venv now, while Claude Desktop is closed and nothing else is using
# this folder. If we skip this, `uv run` builds it lazily on Claude's first
# launch -- but the download (scipy alone is ~35 MB) overruns Claude's startup
# timeout, so Claude disconnects mid-build and a second `uv run` then collides
# with the first installing pywin32 ("being used by another process", os error
# 32). Building once, here, dodges both the timeout and the race, and makes the
# first launch instant. (Mirrors the runtime command in step 5: same --directory
# and --extra, so this is the exact venv `uv run` will reuse.)
#
# uv writes all its progress ("Using CPython...", "Downloading...") to stderr.
# Under the script-wide $ErrorActionPreference='Stop', merging that with 2>&1
# turns uv's first benign status line into a terminating error -- so drop to
# 'Continue' for just this call and judge success by the real exit code.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $uvPath sync --directory $installDir --extra audio 2>&1 |
    ForEach-Object { Write-Host "   $_" -ForegroundColor DarkGray }
$buildExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP

if ($buildExit -eq 0) {
    Write-OK "Environment ready."
} else {
    Write-Warn "Pre-build did not finish (exit $buildExit); Claude will build it on first launch."
    Write-Warn "If the first launch also fails, add '$installDir' to your antivirus exclusions and re-run."
}

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
Write-Host "  The environment was built during install, so Digr is ready right away." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  16 tools available (11 free, 5 Pro)" -ForegroundColor DarkGray
Write-Host "  Pro features: paste your license key to Claude and ask it to" -ForegroundColor DarkGray
Write-Host "  activate Digr Pro (or put the key in %APPDATA%\digr\license.key)" -ForegroundColor DarkGray
Write-Host ""
Read-Host "Press Enter to close"
