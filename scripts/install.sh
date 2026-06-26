#!/usr/bin/env bash
# =============================================================================
# CodeJury - Otomatik kurulum scripti (Linux / macOS)
# =============================================================================
# Sistem onkosullarini (Python, Node.js, Docker, Ollama) kontrol eder,
# eksikleri uyarir, ardindan bagimliliklari kurar, sandbox imajini
# derler, PostgreSQL konteynerini baslatir ve .env dosyasini hazirlar.
#
# Kullanim:
#   bash scripts/install.sh                # Tam kurulum
#   bash scripts/install.sh --demo         # Demo mode (Docker'siz)
#   bash scripts/install.sh --no-sandbox   # Sandbox imajini atla
#   bash scripts/install.sh --no-postgres  # Postgres'i atla
#   bash scripts/install.sh --no-ollama    # Ollama pull atla
#   bash scripts/install.sh --skip-checks  # Onkosul kontrollerini atla
# =============================================================================

set -uo pipefail

# Her zaman repo kokunden calis (scripts/ bir ust dizin)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || { echo "Hata: repo kokune gidilemedi: $REPO_ROOT" >&2; exit 1; }

# Renkler
C_CYAN='\033[36m'
C_GREEN='\033[32m'
C_YELLOW='\033[33m'
C_RED='\033[31m'
C_GRAY='\033[90m'
C_MAGENTA='\033[35m'
C_RESET='\033[0m'

WARNINGS=()
ERRORS=()

step()  { echo -e "\n${C_CYAN}==> $*${C_RESET}"; }
ok()    { echo -e "${C_GREEN}[OK]   ${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}[WARN] ${C_RESET} $*"; WARNINGS+=("$*"); }
err()   { echo -e "${C_RED}[ERROR]${C_RESET} $*"; ERRORS+=("$*"); }
info()  { echo -e "${C_GRAY}[INFO] ${C_RESET} $*"; }

# Argumanlar
SKIP_CHECKS=0
NO_SANDBOX=0
NO_POSTGRES=0
NO_OLLAMA=0
DEMO_MODE=0

for arg in "$@"; do
    case "$arg" in
        --skip-checks) SKIP_CHECKS=1 ;;
        --no-sandbox)  NO_SANDBOX=1 ;;
        --no-postgres) NO_POSTGRES=1 ;;
        --no-ollama)   NO_OLLAMA=1 ;;
        --demo)        DEMO_MODE=1 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) warn "Bilinmeyen parametre: $arg" ;;
    esac
done

has_cmd() { command -v "$1" >/dev/null 2>&1; }

# vercmp: $1 >= $2 ise 0, degilse 1
vercmp_ge() {
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# ---------------------------------------------------------------------------
# 1) Onkosul kontrolleri
# ---------------------------------------------------------------------------

PYTHON_CMD=""

check_python() {
    step "Python 3.11+ kontrol ediliyor"
    for c in python3 python; do
        if has_cmd "$c"; then
            v=$("$c" --version 2>&1 | awk '{print $2}')
            if [ -n "$v" ] && vercmp_ge "$v" "3.11.0"; then
                ok "$c $v"
                PYTHON_CMD="$c"
                return 0
            fi
        fi
    done
    err "Python 3.11+ bulunamadi. https://www.python.org/downloads/"
    return 1
}

check_node() {
    step "Node.js 18+ kontrol ediliyor"
    if ! has_cmd node; then
        err "Node.js bulunamadi. https://nodejs.org/"
        return 1
    fi
    v=$(node --version | sed 's/^v//')
    if vercmp_ge "$v" "18.0.0"; then
        ok "node v$v"
        return 0
    fi
    err "node v$v bulundu ama 18+ gerekli."
    return 1
}

check_npm() {
    if ! has_cmd npm; then
        err "npm bulunamadi (Node.js ile birlikte kurulmali)."
        return 1
    fi
    ok "npm $(npm --version)"
}

check_docker() {
    step "Docker kontrol ediliyor"
    if ! has_cmd docker; then
        warn "Docker bulunamadi. Sandbox havuzu ve PostgreSQL icin Docker sart. https://docs.docker.com/get-docker/"
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        warn "Docker yuklu fakat daemon calismiyor. (sudo) docker servisini baslatin / Docker Desktop'i acin."
        return 1
    fi
    ok "$(docker --version)"
}

check_docker_compose() {
    if has_cmd docker && docker compose version >/dev/null 2>&1; then
        ok "$(docker compose version | head -n1)"
        return 0
    fi
    warn "docker compose bulunamadi (docker compose v2 gerekli)."
    return 1
}

check_ollama() {
    step "Ollama kontrol ediliyor"
    if ! has_cmd ollama; then
        warn "Ollama bulunamadi. LLM destegi icin: https://ollama.com/download"
        return 1
    fi
    if curl -fsS --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
        ok "Ollama servisi calisiyor (http://localhost:11434)"
        return 0
    fi
    warn "Ollama yuklu fakat servis cevap vermiyor. 'ollama serve' calistirin."
    return 1
}

# ---------------------------------------------------------------------------
# 2) .env dosyasi
# ---------------------------------------------------------------------------

prepare_env() {
    step ".env dosyasi hazirlaniyor"
    if [ -f .env ]; then
        ok ".env zaten mevcut, dokunulmadi."
    elif [ -f .env.example ]; then
        cp .env.example .env
        ok ".env, .env.example dosyasindan olusturuldu."
        info "Gerekirse DATABASE_URL, OLLAMA_GENERAL_MODEL ve OLLAMA_CODER_MODEL degerlerini guncelleyin."
    else
        warn ".env.example bulunamadi, .env olusturulamadi."
    fi
}

set_demo_mode() {
    if [ ! -f .env ]; then return; fi
    if grep -qE '^DEMO_MODE=' .env; then
        # macOS sed -i farki icin gecici dosyayla
        sed -i.bak -E 's|^DEMO_MODE=.*|DEMO_MODE=1|' .env && rm -f .env.bak
    else
        printf '\n# Demo Mode\nDEMO_MODE=1\n' >> .env
    fi
    ok ".env: DEMO_MODE=1"
}

# ---------------------------------------------------------------------------
# 3) Bagimliliklar
# ---------------------------------------------------------------------------

# Unix venv: .venv/bin/python | Windows venv (Git Bash): .venv/Scripts/python.exe
venv_python_path() {
    if [ -x ".venv/bin/python" ]; then
        printf '%s' ".venv/bin/python"
    elif [ -x ".venv/Scripts/python.exe" ]; then
        printf '%s' ".venv/Scripts/python.exe"
    else
        printf '%s' ""
    fi
}

venv_needs_recreate() {
    local vp
    vp="$(venv_python_path)"
    if [ -z "$vp" ]; then
        return 0
    fi
    if ! "$vp" -m pip --version >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

install_python_deps() {
    step "Python bagimliliklari kuruluyor (requirements.txt)"
    [ -z "$PYTHON_CMD" ] && PYTHON_CMD="python3"

    recreate_venv() {
        info "Sanal ortam (.venv) olusturuluyor"
        if ! "$PYTHON_CMD" -m venv .venv; then
            err "venv olusturulamadi"
            return 1
        fi
        return 0
    }

    if [ ! -d ".venv" ]; then
        recreate_venv || return
    elif venv_needs_recreate; then
        warn "Bozuk, eksik veya baska makineden kopyalanmis .venv; yeniden olusturuluyor"
        rm -rf .venv
        recreate_venv || return
    fi

    VENV_PY="$(venv_python_path)"
    if [ -z "$VENV_PY" ] || [ ! -x "$VENV_PY" ]; then
        err "venv python bulunamadi (.venv/bin/python veya Scripts/python.exe)"
        return
    fi

    "$VENV_PY" -m pip install --upgrade pip || warn "pip guncelleme uyarisi; devam ediliyor."
    if "$VENV_PY" -m pip install -r requirements.txt; then
        ok "Python bagimliliklari kuruldu."
    else
        err "pip install basarisiz."
    fi
}

install_node_deps() {
    step "Frontend bagimliliklari kuruluyor (npm install)"
    (cd frontend && npm install) && ok "npm install tamamlandi." || err "npm install basarisiz."
}

# ---------------------------------------------------------------------------
# 4) Docker servisleri
# ---------------------------------------------------------------------------

build_sandbox() {
    step "Sandbox imaji derleniyor (agentgrade-sandbox)"
    if ! has_cmd docker; then
        warn "Docker olmadigindan sandbox imaji derlenemez."
        return
    fi
    if docker build -t agentgrade-sandbox sandbox-images/agentgrade/; then
        ok "Sandbox imaji hazir."
    else
        err "docker build basarisiz."
    fi
}

start_postgres() {
    step "PostgreSQL ve Redis servisleri baslatiliyor (docker compose up -d postgres redis)"
    if ! has_cmd docker; then
        warn "Docker olmadigindan PostgreSQL/Redis baslatilamadi. DEMO_MODE=1 kullanmayi deneyin."
        return
    fi
    if docker compose up -d postgres redis; then
        ok "PostgreSQL (5432) ve Redis (6379) ayakta."
    else
        err "docker compose up basarisiz."
    fi
}

pull_ollama_model() {
    step "Ollama modelleri indiriliyor (qwen2.5-coder:14b-instruct-q6_K + qwen2.5:7b)"
    if ! has_cmd ollama; then
        warn "Ollama yok, model cekilemedi."
        return
    fi
    for model in qwen2.5-coder:14b-instruct-q6_K qwen2.5:7b; do
        if ollama pull "$model"; then
            ok "Ollama modeli hazir: $model"
        else
            warn "ollama pull basarisiz ($model), internet baglantisini kontrol edin."
        fi
    done
}

# ---------------------------------------------------------------------------
# Akis
# ---------------------------------------------------------------------------

echo -e "${C_MAGENTA}============================================${C_RESET}"
echo -e "${C_MAGENTA} CodeJury - Otomatik Kurulum (Linux/macOS)${C_RESET}"
echo -e "${C_MAGENTA}============================================${C_RESET}"

if [ "$SKIP_CHECKS" -eq 0 ]; then
    check_python || true
    check_node   || true
    check_npm    || true
    check_docker || true
    check_docker_compose || true
    check_ollama || true

    if [ -z "$PYTHON_CMD" ] || ! has_cmd node || ! has_cmd npm; then
        err "Zorunlu onkosullar eksik. Yukaridaki adimlari tamamlayip tekrar calistirin."
        exit 1
    fi
else
    warn "Onkosul kontrolleri atlandi (--skip-checks)."
fi

prepare_env
install_python_deps
install_node_deps

if [ "$DEMO_MODE" -eq 1 ]; then
    step "Demo Mode: Docker / Ollama adimlari atlaniyor"
    set_demo_mode
else
    [ "$NO_SANDBOX"  -eq 0 ] && build_sandbox
    [ "$NO_POSTGRES" -eq 0 ] && start_postgres
    [ "$NO_OLLAMA"   -eq 0 ] && pull_ollama_model
fi

echo -e "\n${C_MAGENTA}============================================${C_RESET}"
echo -e "${C_MAGENTA} Kurulum Ozeti${C_RESET}"
echo -e "${C_MAGENTA}============================================${C_RESET}"

if [ ${#WARNINGS[@]} -gt 0 ]; then
    echo -e "${C_YELLOW}Uyarilar:${C_RESET}"
    for w in "${WARNINGS[@]}"; do echo -e "  ${C_YELLOW}- $w${C_RESET}"; done
fi
if [ ${#ERRORS[@]} -gt 0 ]; then
    echo -e "${C_RED}Hatalar:${C_RESET}"
    for e in "${ERRORS[@]}"; do echo -e "  ${C_RED}- $e${C_RESET}"; done
    echo -e "\n${C_RED}Kurulum bazi hatalarla bitti.${C_RESET}"
    exit 1
fi

echo -e "\n${C_GREEN}Kurulum tamamlandi!${C_RESET}"
echo -e "Uygulamayi baslatmak icin: ${C_RESET}npm run dev:full"
echo -e "Tarayici: http://localhost:8080"
