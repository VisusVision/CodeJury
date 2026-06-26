<#
.SYNOPSIS
  CodeJury - Otomatik kurulum scripti (Windows / PowerShell).

.DESCRIPTION
  Sistem önkoşullarını (Python, Node.js, Docker, Ollama) kontrol eder,
  eksikleri uyarır, ardından bağımlılıkları kurar, sandbox imajını
  derler, PostgreSQL konteynerini başlatır ve .env dosyasını hazırlar.

.PARAMETER SkipPrereqCheck
  Önkoşul kontrollerini atla (kurulu olduklarını biliyorsan).

.PARAMETER NoSandbox
  Docker sandbox imajını derleme.

.PARAMETER NoPostgres
  docker-compose ile PostgreSQL servisini başlatma.

.PARAMETER NoOllamaPull
  Ollama modelini indirme adımını atla.

.PARAMETER DemoMode
  PostgreSQL/Docker olmadan demo mode için hızlı kurulum
  (yalnızca Python + Node bağımlılıklarını kurar).

.EXAMPLE
  .\scripts\install.ps1
  .\scripts\install.ps1 -DemoMode
  .\scripts\install.ps1 -NoSandbox -NoPostgres
#>

[CmdletBinding()]
param(
    [switch]$SkipPrereqCheck,
    [switch]$NoSandbox,
    [switch]$NoPostgres,
    [switch]$NoOllamaPull,
    [switch]$DemoMode
)

$ErrorActionPreference = "Stop"
# Her zaman repo kokunden calis (scripts/ klasorunun ust dizini)
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

$script:Warnings = @()
$script:Errors   = @()

# Renkli logging yardımcıları
function Write-Step($msg)    { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn2($msg)   { Write-Host "[WARN]  $msg" -ForegroundColor Yellow; $script:Warnings += $msg }
function Write-Err2($msg)    { Write-Host "[ERROR] $msg" -ForegroundColor Red;    $script:Errors   += $msg }
function Write-Info($msg)    { Write-Host "[INFO]  $msg" -ForegroundColor Gray }

# Komut var mı?
function Test-Command($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

# Versiyon karşılaştırması (string -> [version])
function Compare-Version([string]$current, [string]$min) {
    try   { return ([version]$current) -ge ([version]$min) }
    catch { return $false }
}

# ---------------------------------------------------------------------------
# 1) Önkoşul kontrolleri
# ---------------------------------------------------------------------------

function Test-Python {
    Write-Step "Python 3.11+ kontrol ediliyor"
    $candidates = @("python", "py")
    foreach ($c in $candidates) {
        if (Test-Command $c) {
            try {
                $verRaw = & $c --version 2>&1
                if ($verRaw -match "Python (\d+\.\d+\.\d+)") {
                    $ver = $Matches[1]
                    if (Compare-Version $ver "3.11.0") {
                        Write-Ok "$c $ver"
                        $script:PythonCmd = $c
                        return $true
                    } else {
                        Write-Warn2 "$c $ver bulundu ama 3.11+ gerekli."
                    }
                }
            } catch { }
        }
    }
    Write-Err2 "Python 3.11+ bulunamadi. https://www.python.org/downloads/ adresinden kurun."
    return $false
}

function Test-Node {
    Write-Step "Node.js 18+ kontrol ediliyor"
    if (-not (Test-Command "node")) {
        Write-Err2 "Node.js bulunamadi. https://nodejs.org/ adresinden 18+ kurun."
        return $false
    }
    $ver = (& node --version) -replace "^v",""
    if (Compare-Version $ver "18.0.0") {
        Write-Ok "node v$ver"
        return $true
    } else {
        Write-Err2 "node v$ver bulundu ama 18+ gerekli."
        return $false
    }
}

function Test-Npm {
    if (-not (Test-Command "npm")) {
        Write-Err2 "npm bulunamadi (Node.js ile birlikte kurulmali)."
        return $false
    }
    $ver = (& npm --version)
    Write-Ok "npm $ver"
    return $true
}

function Test-Docker {
    Write-Step "Docker Desktop kontrol ediliyor"
    if (-not (Test-Command "docker")) {
        Write-Warn2 "Docker bulunamadi. Sandbox havuzu ve PostgreSQL icin Docker Desktop sart. https://www.docker.com/products/docker-desktop/"
        return $false
    }
    try {
        $null = & docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 "Docker yuklu fakat daemon calismiyor. Docker Desktop'i baslatin."
            return $false
        }
        $ver = (& docker --version)
        Write-Ok $ver
        return $true
    } catch {
        Write-Warn2 "Docker calistirilamadi: $_"
        return $false
    }
}

function Test-DockerCompose {
    if (Test-Command "docker") {
        $null = & docker compose version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok ((& docker compose version) | Select-Object -First 1)
            return $true
        }
    }
    Write-Warn2 "docker compose bulunamadi (Docker Desktop guncel olmali)."
    return $false
}

function Test-Ollama {
    Write-Step "Ollama kontrol ediliyor"
    if (-not (Test-Command "ollama")) {
        Write-Warn2 "Ollama bulunamadi. LLM destegi icin: https://ollama.com/download"
        return $false
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        Write-Ok "Ollama servisi calisiyor (http://localhost:11434)"
        return $true
    } catch {
        Write-Warn2 "Ollama yuklu fakat servis cevap vermiyor. 'ollama serve' calistirin."
        return $false
    }
}

# ---------------------------------------------------------------------------
# 2) .env dosyasini hazirla
# ---------------------------------------------------------------------------

function Initialize-EnvFile {
    Write-Step ".env dosyasi hazirlaniyor"
    $envPath     = Join-Path $PWD ".env"
    $exampleFile = Join-Path $PWD ".env.example"
    if (Test-Path $envPath) {
        Write-Ok ".env zaten mevcut, dokunulmadi."
    } elseif (Test-Path $exampleFile) {
        Copy-Item $exampleFile $envPath
        Write-Ok ".env, .env.example dosyasindan olusturuldu."
        Write-Info "Gerekirse DATABASE_URL, OLLAMA_GENERAL_MODEL ve OLLAMA_CODER_MODEL degerlerini guncelleyin."
    } else {
        Write-Warn2 ".env.example bulunamadi, .env olusturulamadi."
    }
}

# ---------------------------------------------------------------------------
# 3) Bagimliliklar
# ---------------------------------------------------------------------------

function Install-PythonDeps {
    Write-Step "Python bagimliliklari kuruluyor (requirements.txt)"
    if (-not $script:PythonCmd) { $script:PythonCmd = "python" }

    $venv = Join-Path $PWD ".venv"
    $venvPy = Join-Path $venv "Scripts\python.exe"
    $needsNewVenv = $false

    if (-not (Test-Path $venv)) {
        $needsNewVenv = $true
    } elseif (-not (Test-Path $venvPy)) {
        Write-Info "Eksik .venv (python.exe yok); yeniden olusturuluyor"
        Remove-Item -Recurse -Force $venv
        $needsNewVenv = $true
    } else {
        $null = & $venvPy -m pip --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Info "Bozuk veya baska PC'den kopyalanmis .venv; yeniden olusturuluyor"
            Remove-Item -Recurse -Force $venv
            $needsNewVenv = $true
        }
    }

    if ($needsNewVenv) {
        Write-Info "Sanal ortam (.venv) olusturuluyor"
        & $script:PythonCmd -m venv .venv
        if ($LASTEXITCODE -ne 0) { Write-Err2 "venv olusturulamadi"; return }
        $venvPy = Join-Path $venv "Scripts\python.exe"
    }

    if (-not (Test-Path $venvPy)) {
        Write-Err2 "venv python bulunamadi: $venvPy"
        return
    }

    & $venvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "pip guncelleme uyarisi; bagimlilik kurulumuna devam ediliyor."
    }

    & $venvPy -m pip install -r requirements.txt
    if ($LASTEXITCODE -eq 0) { Write-Ok "Python bagimliliklari kuruldu." }
    else                     { Write-Err2 "pip install basarisiz." }
}

function Install-NodeDeps {
    Write-Step "Frontend bagimliliklari kuruluyor (npm install)"
    Push-Location frontend
    try {
        & npm install
        if ($LASTEXITCODE -eq 0) { Write-Ok "npm install tamamlandi." }
        else                     { Write-Err2 "npm install basarisiz." }
    } finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# 4) Docker servisleri
# ---------------------------------------------------------------------------

function Build-SandboxImage {
    Write-Step "Sandbox imaji derleniyor (agentgrade-sandbox)"
    if (-not (Test-Command "docker")) {
        Write-Warn2 "Docker olmadigindan sandbox imaji derlenemez."
        return
    }
    & docker build -t agentgrade-sandbox sandbox-images/agentgrade/
    if ($LASTEXITCODE -eq 0) { Write-Ok "Sandbox imaji hazir." }
    else                     { Write-Err2 "docker build basarisiz." }
}

function Start-Postgres {
    Write-Step "PostgreSQL ve Redis servisleri baslatiliyor (docker compose up -d postgres redis)"
    if (-not (Test-Command "docker")) {
        Write-Warn2 "Docker olmadigindan PostgreSQL/Redis baslatilamadi. DEMO_MODE=1 kullanmayi deneyin."
        return
    }
    & docker compose up -d postgres redis
    if ($LASTEXITCODE -eq 0) { Write-Ok "PostgreSQL (5432) ve Redis (6379) ayakta." }
    else                     { Write-Err2 "docker compose up basarisiz." }
}

function Pull-OllamaModel {
    Write-Step "Ollama modelleri indiriliyor (qwen2.5-coder:14b-instruct-q6_K + qwen2.5:7b)"
    if (-not (Test-Command "ollama")) {
        Write-Warn2 "Ollama yok, model cekilemedi."
        return
    }
    $models = @("qwen2.5-coder:14b-instruct-q6_K", "qwen2.5:7b")
    foreach ($model in $models) {
        & ollama pull $model
        if ($LASTEXITCODE -eq 0) { Write-Ok "Ollama modeli hazir: $model" }
        else                     { Write-Warn2 "ollama pull basarisiz ($model), internet baglantisini kontrol edin." }
    }
}

# ---------------------------------------------------------------------------
# Akis
# ---------------------------------------------------------------------------

Write-Host "============================================" -ForegroundColor Magenta
Write-Host " CodeJury - Otomatik Kurulum (Windows)" -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Magenta

if (-not $SkipPrereqCheck) {
    $okPython = Test-Python
    $okNode   = Test-Node
    $okNpm    = Test-Npm
    $okDocker = Test-Docker
    $null     = Test-DockerCompose
    $null     = Test-Ollama

    if (-not ($okPython -and $okNode -and $okNpm)) {
        Write-Err2 "Zorunlu onkosullar eksik. Lutfen yukaridaki adimlari tamamlayip tekrar calistirin."
        exit 1
    }
} else {
    Write-Warn2 "Onkosul kontrolleri atlandi (-SkipPrereqCheck)."
}

Initialize-EnvFile
Install-PythonDeps
Install-NodeDeps

if ($DemoMode) {
    Write-Step "DemoMode aktif: Docker/Ollama adimlari atlaniyor"
    # .env'de DEMO_MODE=1 ayarla
    $envPath = Join-Path $PWD ".env"
    if (Test-Path $envPath) {
        $content = Get-Content $envPath -Raw
        if ($content -match "(?m)^DEMO_MODE=") {
            $content = [regex]::Replace($content, "(?m)^DEMO_MODE=.*$", "DEMO_MODE=1")
        } else {
            $content = $content.TrimEnd() + "`r`n`r`n# Demo Mode`r`nDEMO_MODE=1`r`n"
        }
        Set-Content -Path $envPath -Value $content -NoNewline
        Write-Ok ".env: DEMO_MODE=1"
    }
} else {
    if (-not $NoSandbox)  { Build-SandboxImage }
    if (-not $NoPostgres) { Start-Postgres }
    if (-not $NoOllamaPull) { Pull-OllamaModel }
}

# Ozet
Write-Host "`n============================================" -ForegroundColor Magenta
Write-Host " Kurulum Ozeti" -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Magenta

if ($script:Warnings.Count -gt 0) {
    Write-Host "Uyarilar:" -ForegroundColor Yellow
    $script:Warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
}
if ($script:Errors.Count -gt 0) {
    Write-Host "Hatalar:" -ForegroundColor Red
    $script:Errors | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "`nKurulum bazi hatalarla bitti. Lutfen yukaridaki mesajlari giderip tekrar calistirin." -ForegroundColor Red
    exit 1
}

Write-Host "`nKurulum tamamlandi!" -ForegroundColor Green
Write-Host "Uygulamayi baslatmak icin:" -ForegroundColor Green
Write-Host "  npm run dev:full" -ForegroundColor White
Write-Host "Tarayici: http://localhost:8080" -ForegroundColor White
