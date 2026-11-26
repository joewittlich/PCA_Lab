#!/usr/bin/env bash
# Bootstrap a fresh macOS or Linux machine for the SRE PCA lab.
# Installs ONLY what is missing: git, curl, Docker (+ Compose v2), uv (which manages Python).
# Safe to re-run.  Usage:  ./scripts/bootstrap.sh [--yes]
set -euo pipefail

YES=0
[ "${1:-}" = "--yes" ] && YES=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OS="$(uname -s)"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

confirm() {
  [ "$YES" = 1 ] && return 0
  read -r -p "  $1 [Y/n] " ans
  case "${ans:-y}" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

SUDO=""
if [ "$(id -u)" -ne 0 ] && have sudo; then SUDO="sudo"; fi

# --------------------------------------------------------------------------- macOS
bootstrap_macos() {
  say "macOS detected"
  if ! have brew; then
    warn "Homebrew not found."
    if confirm "Install Homebrew (https://brew.sh)?"; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      # Apple Silicon vs Intel prefix
      if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
      if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
    else
      echo "Homebrew is required for this script on macOS. Aborting."; exit 1
    fi
  fi
  ok "Homebrew $(brew --version | head -1)"

  if have git; then ok "git $(git --version)"; else say "Installing git"; brew install git; fi
  if have uv;  then ok "uv $(uv --version)";   else say "Installing uv"; brew install uv; fi

  if have docker; then
    ok "docker CLI present"
  else
    say "Installing Docker Desktop (cask)"
    warn "Alternatives if you can't use Docker Desktop's license: OrbStack (brew install --cask orbstack) or Colima."
    brew install --cask docker
  fi
  if ! docker info >/dev/null 2>&1; then
    warn "Docker engine not running. Opening Docker Desktop - accept the prompts, wait for 'Engine running'."
    open -a Docker || true
  fi
}

# --------------------------------------------------------------------------- Linux
bootstrap_linux() {
  local distro
  distro="$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release 2>/dev/null | tr -d '"')"
  say "Linux detected (${distro:-unknown distro})"
  if grep -qi microsoft /proc/version 2>/dev/null; then
    warn "WSL detected. Recommended: install Docker Desktop on Windows and enable WSL integration"
    warn "(Docker Desktop > Settings > Resources > WSL integration) instead of installing Docker inside WSL."
  fi

  if have apt-get; then
    local pkgs=()
    have git  || pkgs+=(git)
    have curl || pkgs+=(curl)
    have make || pkgs+=(make)
    pkgs+=(ca-certificates)
    say "apt: installing ${pkgs[*]}"
    $SUDO apt-get update -y
    $SUDO apt-get install -y "${pkgs[@]}"
  elif have dnf; then
    $SUDO dnf install -y git curl make
  elif have pacman; then
    $SUDO pacman -Sy --needed --noconfirm git curl make
  else
    warn "Unknown package manager: install git, curl and make yourself."
  fi
  ok "git $(git --version 2>/dev/null || echo missing)"

  if have docker && docker compose version >/dev/null 2>&1; then
    ok "docker + compose v2 present"
  else
    say "Installing Docker Engine + Compose plugin via the official script (https://get.docker.com)"
    if confirm "Run the official Docker install script with sudo?"; then
      curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
      $SUDO sh /tmp/get-docker.sh
    else
      warn "Skipped Docker install."
    fi
  fi

  if have docker; then
    if have systemctl && [ -d /run/systemd/system ]; then
      $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
    fi
    if [ "$(id -u)" -ne 0 ] && ! id -nG "$USER" | grep -qw docker; then
      say "Adding $USER to the 'docker' group (so you don't need sudo)"
      $SUDO usermod -aG docker "$USER" || true
      warn "Log out and back in (or run 'newgrp docker') for the group change to apply."
    fi
  fi

  if have uv; then
    ok "uv $(uv --version)"
  else
    say "Installing uv (https://astral.sh/uv)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
}

case "$OS" in
  Darwin) bootstrap_macos ;;
  Linux)  bootstrap_linux ;;
  *) printf 'Unsupported OS: %s (on Windows use scripts\\bootstrap.ps1)\n' "$OS"; exit 1 ;;
esac

# --------------------------------------------------------------------------- Python env (all OSes)
say "Python environment"
if have uv; then
  cd "$ROOT"
  uv python install 3.12
  uv sync
  ok "Python deps installed into $ROOT/.venv"
else
  warn "uv not on PATH yet - open a new terminal and run: uv sync"
fi

# --------------------------------------------------------------------------- summary
say "Checks"
if have git; then ok "git"; else warn "git missing"; fi
if have uv; then ok "uv"; else warn "uv missing (open a new terminal?)"; fi
if have docker; then
  ok "docker CLI"
  if docker compose version >/dev/null 2>&1; then ok "docker compose $(docker compose version --short)"; else warn "docker compose v2 missing"; fi
  if docker info >/dev/null 2>&1; then ok "docker engine reachable"; else warn "docker engine NOT reachable yet (start Docker / re-login for group)"; fi
else
  warn "docker missing"
fi
echo
echo "Next:  ./scripts/lab.sh up        (then open http://localhost:3000, admin/admin)"
