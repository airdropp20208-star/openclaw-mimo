# Phantom Node - Hermes Setup Script
# Installs Python + Hermes + configures Mimo 2.5

param(
    [string]$MimoApiKey = ""
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "   PHANTOM NODE - HERMES SETUP v1.0" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# --- [1/6] Install Python 3.11 ---
Write-Host "[1/6] Installing Python 3.11..." -ForegroundColor Yellow
if (!(Test-Path "C:\Python311\python.exe")) {
    $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    Invoke-WebRequest -Uri $pyUrl -OutFile "C:\python-installer.exe"
    Start-Process "C:\python-installer.exe" -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_pip=1" -Wait
    Remove-Item "C:\python-installer.exe" -Force
    Write-Host "  -> Python 3.11 installed" -ForegroundColor Green
} else {
    Write-Host "  -> Python 3.11 already installed" -ForegroundColor Green
}

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$env:PATH = "C:\Python311;C:\Python311\Scripts;" + $env:PATH

# Verify
python --version 2>&1 | ForEach-Object { Write-Host "  -> $_" -ForegroundColor Green }

# --- [2/6] Install Hermes ---
Write-Host "`n[2/6] Installing Hermes Agent..." -ForegroundColor Yellow
pip install --upgrade pip 2>&1 | Out-Null
pip install hermes-agent 2>&1 | ForEach-Object { 
    if ($_ -match "Successfully") { Write-Host "  -> $_" -ForegroundColor Green }
}
hermes --version 2>&1 | ForEach-Object { Write-Host "  -> $_" -ForegroundColor Green }

# --- [3/6] Create Hermes config ---
Write-Host "`n[3/6] Configuring Hermes for Mimo 2.5..." -ForegroundColor Yellow

$hermesHome = "$env:USERPROFILE\.hermes"
$configDir = "$hermesHome"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

# Generate config.yaml
$configYaml = @"
model:
  default: mimo-v2.5
  provider: xiaomi
  base_url: https://api.xiaomimimo.com/v1
providers: {}
fallback_providers: []
credential_pool_strategies:
  xiaomi: fill_first
toolsets:
- hermes-cli
agent:
  max_turns: 90
  gateway_timeout: 1800
  restart_drain_timeout: 180
  api_max_retries: 3
  service_tier: ''
  tool_use_enforcement: auto
  gateway_timeout_warning: 900
  clarify_timeout: 600
  gateway_notify_interval: 180
  gateway_auto_continue_freshness: 3600
  image_input_mode: auto
  disabled_toolsets: []
terminal:
  backend: local
  modal_mode: auto
  cwd: .
  timeout: 180
  env_passthrough: []
  shell_init_files: []
  auto_source_bashrc: true
  persistent_shell: true
display:
  compact: false
  personality: kawaii
  language: en
  streaming: false
  timestamps: false
privacy:
  redact_pii: false
security:
  allow_private_urls: false
  redact_secrets: true
  allow_lazy_installs: true
cron:
  wrap_response: true
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
  provider: ''
context:
  engine: compressor
compression:
  enabled: true
  threshold: 0.5
  target_ratio: 0.2
  protect_last_n: 20
  hygiene_hard_message_limit: 400
platform_toolsets:
  cli:
  - browser
  - clarify
  - code_execution
  - cronjob
  - delegation
  - file
  - image_gen
  - memory
  - session_search
  - skills
  - terminal
  - todo
  - tts
  - vision
  - web
_config_version: 23
"@

$configYaml | Out-File -FilePath "$configDir\config.yaml" -Encoding utf8 -Force
Write-Host "  -> config.yaml created" -ForegroundColor Green

# --- [4/6] Configure API key ---
Write-Host "`n[4/6] Setting up API key..." -ForegroundColor Yellow

if ($MimoApiKey -ne "") {
    # Write to .env file
    "XIAOMI_API_KEY=$MimoApiKey" | Out-File -FilePath "$hermesHome\.env" -Encoding utf8 -Force
    Write-Host "  -> API key saved to .env" -ForegroundColor Green
} else {
    # Create placeholder
    "# Replace with your Xiaomi Mimo API key`nXIAOMI_API_KEY=YOUR_KEY_HERE" | Out-File -FilePath "$hermesHome\.env" -Encoding utf8 -Force
    Write-Host "  -> Placeholder .env created (edit ~/.hermes/.env)" -ForegroundColor Yellow
}

# Also set as system env var for the session
if ($MimoApiKey -ne "") {
    [System.Environment]::SetEnvironmentVariable("XIAOMI_API_KEY", $MimoApiKey, "User")
    $env:XIAOMI_API_KEY = $MimoApiKey
}

# --- [5/6] Verify installation ---
Write-Host "`n[5/6] Verifying installation..." -ForegroundColor Yellow

$hermesCheck = hermes --version 2>&1
Write-Host "  -> Hermes: $hermesCheck" -ForegroundColor Green

# Test basic functionality (non-interactive)
Write-Host "  -> Config path: $hermesHome\config.yaml" -ForegroundColor Green
Write-Host "  -> .env path: $hermesHome\.env" -ForegroundColor Green

# --- [6/6] Create startup script ---
Write-Host "`n[6/6] Creating startup script..." -ForegroundColor Yellow

$startupScript = @'
@echo off
title Phantom Node - Hermes
echo.
echo ========================================
echo    PHANTOM NODE - HERMES MODE
echo ========================================
echo.
echo Starting Hermes with Mimo 2.5...
echo.
hermes
pause
'@

$startupScript | Out-File -FilePath "C:\phantom-start.bat" -Encoding ascii -Force
Write-Host "  -> C:\phantom-start.bat created" -ForegroundColor Green

# Create desktop shortcut
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = "$desktop\Phantom Node.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "C:\phantom-start.bat"
$shortcut.WorkingDirectory = "C:\"
$shortcut.Description = "Launch Phantom Node Hermes"
$shortcut.Save()
Write-Host "  -> Desktop shortcut created" -ForegroundColor Green

# --- Done ---
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "   SETUP COMPLETE!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Hermes path:  $(Get-Command hermes -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)"
Write-Host "  Config:       $hermesHome\config.yaml"
Write-Host "  API Key:      $hermesHome\.env"
Write-Host "  Start:        C:\phantom-start.bat"
Write-Host ""
Write-Host "  To use: Edit .env with your Mimo API key," -ForegroundColor Yellow
Write-Host "  then double-click 'Phantom Node' on Desktop." -ForegroundColor Yellow
Write-Host ""
