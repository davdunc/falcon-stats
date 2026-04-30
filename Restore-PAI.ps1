<#
.SYNOPSIS
    Restore PAI system to a new Windows/WSL2 desktop

.DESCRIPTION
    Restores David Duncan's PAI trading infrastructure from:
    - S3 backup (PAI system: skills, hooks, Algorithm, MEMORY, Substrate)
    - GitHub repos (falcon-stats, falcon, das-cmd-test, pai-framework)
    - DynamoDB (trading data — cloud-native, no restore needed)

    Then validates .env credentials and tests connectivity.

.PARAMETER WslDistro
    WSL2 distro name (default: FedoraLinux-42)

.PARAMETER SkipRestore
    Skip S3 restore, only validate

.EXAMPLE
    .\Restore-PAI.ps1
    .\Restore-PAI.ps1 -SkipRestore
    .\Restore-PAI.ps1 -WslDistro "Ubuntu"
#>

param(
    [string]$WslDistro = "FedoraLinux-42",
    [switch]$SkipRestore
)

$ErrorActionPreference = "Continue"

function Write-Step { param($msg) Write-Host "`n[$([DateTime]::Now.ToString('HH:mm:ss'))] $msg" -ForegroundColor Cyan }
function Write-OK { param($msg) Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Fail { param($msg) Write-Host "  FAIL: $msg" -ForegroundColor Red }
function Write-Warn { param($msg) Write-Host "  WARN: $msg" -ForegroundColor Yellow }

function Invoke-Wsl {
    param([string]$Command)
    wsl -d $WslDistro -- bash -c $Command 2>&1
}

# ============================================================
Write-Host ""
Write-Host "  FALCON PAI RESTORE" -ForegroundColor Cyan
Write-Host "  ==================" -ForegroundColor DarkCyan
Write-Host "  Restoring PAI trading infrastructure to this machine"
Write-Host ""

# ============================================================
# Step 0: Check prerequisites
# ============================================================
Write-Step "Checking prerequisites..."

# WSL
$wslList = wsl -l -v 2>&1 | Out-String
if ($wslList -match $WslDistro) {
    Write-OK "WSL distro '$WslDistro' found"
} else {
    Write-Fail "WSL distro '$WslDistro' not found. Available:"
    wsl -l -v
    exit 1
}

# AWS CLI (Windows side for credential copy)
$awsWindows = Get-Command aws -ErrorAction SilentlyContinue
if ($awsWindows) {
    Write-OK "AWS CLI found on Windows"
} else {
    Write-Warn "AWS CLI not on Windows PATH — will install in WSL"
}

# GitHub CLI
$ghWindows = Get-Command gh -ErrorAction SilentlyContinue
if ($ghWindows) {
    Write-OK "GitHub CLI found"
} else {
    Write-Warn "GitHub CLI not found — install from https://cli.github.com/"
}

# Check AWS credentials exist on Windows
if (Test-Path "$env:USERPROFILE\.aws\credentials") {
    Write-OK "AWS credentials found at $env:USERPROFILE\.aws\"
} else {
    Write-Fail "No AWS credentials at $env:USERPROFILE\.aws\ — configure with 'aws configure'"
    exit 1
}

# ============================================================
# Step 1: Copy AWS credentials to WSL
# ============================================================
Write-Step "Copying AWS credentials to WSL..."

Invoke-Wsl "mkdir -p ~/.aws"
Invoke-Wsl "cp /mnt/c/Users/$env:USERNAME/.aws/config ~/.aws/config 2>/dev/null"
Invoke-Wsl "cp /mnt/c/Users/$env:USERNAME/.aws/credentials ~/.aws/credentials 2>/dev/null"

$identity = Invoke-Wsl "~/.local/bin/aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null || aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null"
if ($identity -match "arn:aws") {
    Write-OK "AWS identity: $($identity.Trim())"
} else {
    # Try installing AWS CLI in WSL
    Write-Warn "AWS CLI not working in WSL — installing..."
    Invoke-Wsl "pip3 install --user awscli 2>&1 | tail -1"
    Invoke-Wsl "cp /mnt/c/Users/$env:USERNAME/.aws/config ~/.aws/config"
    Invoke-Wsl "cp /mnt/c/Users/$env:USERNAME/.aws/credentials ~/.aws/credentials"
    $identity = Invoke-Wsl "~/.local/bin/aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null"
    if ($identity -match "arn:aws") {
        Write-OK "AWS identity: $($identity.Trim())"
    } else {
        Write-Fail "Cannot authenticate to AWS"
        exit 1
    }
}

if (-not $SkipRestore) {
    # ============================================================
    # Step 2: Restore PAI from S3
    # ============================================================
    Write-Step "Restoring PAI system from S3 (this may take a minute)..."

    $result = Invoke-Wsl "~/.local/bin/aws s3 sync s3://davdunc-pai-backup/claude/ ~/.claude/ --region us-east-2 2>&1 | tail -3"
    Write-Host "  $result"

    # Verify restore
    $skillCount = Invoke-Wsl "ls ~/.claude/skills/ 2>/dev/null | wc -l"
    $hookCount = Invoke-Wsl "ls ~/.claude/hooks/*.hook.ts 2>/dev/null | wc -l"
    if ([int]$skillCount.Trim() -gt 0) {
        Write-OK "PAI restored: $($skillCount.Trim()) skills, $($hookCount.Trim()) hooks"
    } else {
        Write-Fail "PAI restore may have failed — check ~/.claude/"
    }

    # ============================================================
    # Step 3: Clone repositories
    # ============================================================
    Write-Step "Cloning repositories..."

    $repos = @("falcon-stats", "falcon", "das-cmd-test", "pai-framework")
    Invoke-Wsl "mkdir -p ~/Projects/Falcon"

    foreach ($repo in $repos) {
        $exists = Invoke-Wsl "test -d ~/Projects/Falcon/$repo && echo YES || echo NO"
        if ($exists.Trim() -eq "YES") {
            Write-OK "$repo already cloned — pulling latest"
            Invoke-Wsl "cd ~/Projects/Falcon/$repo && git pull --quiet 2>&1"
        } else {
            Write-Host "  Cloning davdunc/$repo..."
            Invoke-Wsl "cd ~/Projects/Falcon && gh repo clone davdunc/$repo 2>&1 | tail -1"
        }
    }

    # ============================================================
    # Step 4: Install Python dependencies
    # ============================================================
    Write-Step "Installing Python dependencies..."

    Invoke-Wsl "cd ~/Projects/Falcon/falcon-stats && pip3 install -e . --quiet 2>&1 | tail -1"
    Write-OK "falcon-stats installed"

    # ============================================================
    # Step 5: Build falcon-stats container
    # ============================================================
    Write-Step "Building falcon-stats container..."

    $podman = Invoke-Wsl "which podman 2>/dev/null"
    if ($podman) {
        Invoke-Wsl "cd ~/Projects/Falcon/falcon-stats && podman build -t falcon-stats -f Containerfile . 2>&1 | tail -3"
        Write-OK "Container built: falcon-stats (Fedora 44)"
    } else {
        Write-Warn "Podman not installed — skipping container build"
        Write-Warn "Install with: sudo dnf install -y podman"
    }
}

# ============================================================
# Step 6: Validate .env credentials
# ============================================================
Write-Step "Validating .env credentials..."

$envExists = Invoke-Wsl "test -f ~/.claude/.env && echo YES || echo NO"
if ($envExists.Trim() -ne "YES") {
    Write-Fail ".env file not found at ~/.claude/.env"
    Write-Host ""
    Write-Host "  Create it with:" -ForegroundColor Yellow
    Write-Host '  cat > ~/.claude/.env << EOF'
    Write-Host '  GITLAB_TOKEN=<your GitLab PAT>'
    Write-Host '  FRED_API_KEY=<your FRED key>'
    Write-Host '  EIA_API_KEY=<your EIA key>'
    Write-Host '  POLYGON_API_KEY=<your Polygon key>'
    Write-Host '  FINVIZ_API_KEY=<your Finviz key>'
    Write-Host '  MASSIVE_S3_ACCESS_KEY=<your Massive access key>'
    Write-Host '  MASSIVE_S3_SECRET_KEY=<your Massive secret key>'
    Write-Host '  YOUTUBE_API_KEY=<your YouTube Data API key>'
    Write-Host '  EOF'
} else {
    $requiredKeys = @(
        "GITLAB_TOKEN",
        "FRED_API_KEY",
        "EIA_API_KEY",
        "POLYGON_API_KEY",
        "FINVIZ_API_KEY",
        "MASSIVE_S3_ACCESS_KEY",
        "MASSIVE_S3_SECRET_KEY",
        "YOUTUBE_API_KEY"
    )

    $missing = @()
    $found = 0

    foreach ($key in $requiredKeys) {
        $hasKey = Invoke-Wsl "grep -q '$key=' ~/.claude/.env && echo YES || echo NO"
        $value = Invoke-Wsl "grep '$key=' ~/.claude/.env | cut -d= -f2-"
        if ($hasKey.Trim() -eq "YES" -and $value.Trim().Length -gt 0) {
            $masked = $value.Trim().Substring(0, [Math]::Min(6, $value.Trim().Length)) + "..."
            Write-OK "$key = $masked"
            $found++
        } else {
            Write-Fail "$key — MISSING"
            $missing += $key
        }
    }

    if ($missing.Count -eq 0) {
        Write-OK "All $found credentials present"
    } else {
        Write-Warn "$($missing.Count) credentials missing: $($missing -join ', ')"
    }
}

# ============================================================
# Step 7: Test connectivity
# ============================================================
Write-Step "Testing connectivity..."

# DynamoDB
$dbTest = Invoke-Wsl "cd ~/Projects/Falcon/falcon-stats && python3 -c `"from falcon_stats import db; trades = db.get_round_trips('2026-04-24'); print(len(trades))`" 2>/dev/null"
if ($dbTest.Trim() -match '^\d+$' -and [int]$dbTest.Trim() -gt 0) {
    Write-OK "DynamoDB: $($dbTest.Trim()) round-trips for Apr 24"
} else {
    Write-Fail "DynamoDB: cannot read falcon-trades table"
}

# FRED API
$fredTest = Invoke-Wsl "source ~/.claude/.env 2>/dev/null; curl -s `"https://api.stlouisfed.org/fred/series?series_id=GDP&api_key=`$FRED_API_KEY&file_type=json`" 2>/dev/null | python3 -c `"import sys,json; d=json.load(sys.stdin); print('OK' if 'seriess' in d else 'FAIL')`" 2>/dev/null"
if ($fredTest.Trim() -eq "OK") {
    Write-OK "FRED API: connected"
} else {
    Write-Warn "FRED API: could not verify"
}

# Polygon API
$polyTest = Invoke-Wsl "source ~/.claude/.env 2>/dev/null; curl -s `"https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2026-04-21/2026-04-21?apiKey=`$POLYGON_API_KEY`" 2>/dev/null | python3 -c `"import sys,json; d=json.load(sys.stdin); print(d.get('status','FAIL'))`" 2>/dev/null"
if ($polyTest.Trim() -eq "OK") {
    Write-OK "Polygon API: connected"
} else {
    Write-Warn "Polygon API: could not verify"
}

# GitLab
$gitlabTest = Invoke-Wsl "source ~/.claude/.env 2>/dev/null; curl -s --header `"PRIVATE-TOKEN: `$GITLAB_TOKEN`" `"https://gitlab.com/api/v4/user`" 2>/dev/null | python3 -c `"import sys,json; d=json.load(sys.stdin); print(d.get('username','FAIL'))`" 2>/dev/null"
if ($gitlabTest.Trim() -eq "davdunc") {
    Write-OK "GitLab: authenticated as $($gitlabTest.Trim())"
} else {
    Write-Warn "GitLab: could not verify"
}

# ============================================================
# Summary
# ============================================================
Write-Host ""
Write-Host "  ===========================================" -ForegroundColor Cyan
Write-Host "  RESTORE COMPLETE" -ForegroundColor Green
Write-Host "  ===========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  PAI System:    ~/.claude/ (skills, hooks, Algorithm, MEMORY)" -ForegroundColor White
Write-Host "  Trading Data:  DynamoDB falcon-trades (cloud-native)" -ForegroundColor White
Write-Host "  Repos:         ~/Projects/Falcon/ (falcon-stats, falcon, das-cmd-test)" -ForegroundColor White
Write-Host "  Container:     podman run falcon-stats <command>" -ForegroundColor White
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Yellow
Write-Host "    1. Open Claude Code: claude" -ForegroundColor White
Write-Host "    2. Login: /login" -ForegroundColor White
Write-Host "    3. Test: 'build my morning game plan'" -ForegroundColor White
Write-Host ""
