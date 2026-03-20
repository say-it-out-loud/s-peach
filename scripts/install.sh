#!/usr/bin/env bash
# s-peach installer — curl -fsSL <url>/install.sh | bash
#
# Detects OS, installs system dependencies (Linux only),
# installs uv if needed, and installs s-peach via uv tool.
#
# Options:
#   WITH_CHATTERBOX=1  Include chatterbox voice cloning support
set -euo pipefail

# --- Constants ---

PACKAGE="s-peach-tts"
UV_INSTALL_URL="https://astral.sh/uv/install.sh"
# chatterbox-tts overpins numpy/torch — these overrides are needed until upstream fixes
CHATTERBOX_OVERRIDES="numpy>=2.0
torch>=2.6.0
torchaudio>=2.6.0"

# --- Helpers ---

info()  { printf '\033[1;34m==> %s\033[0m\n' "$1"; }
warn()  { printf '\033[1;33m==> WARNING: %s\033[0m\n' "$1" >&2; }
error() { printf '\033[1;31m==> ERROR: %s\033[0m\n' "$1" >&2; exit 1; }

# --- OS detection ---

detect_os() {
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux)  echo "linux" ;;
        *)      error "Unsupported OS: $(uname -s). Only macOS and Linux are supported." ;;
    esac
}

# --- Linux dependency installation ---

install_linux_deps() {
    info "Installing system dependencies (portaudio)..."

    if command -v apt-get >/dev/null 2>&1; then
        # Debian/Ubuntu
        if dpkg -l libportaudio2 >/dev/null 2>&1; then
            info "libportaudio2 already installed, skipping."
        else
            info "Installing libportaudio2 via apt..."
            sudo apt-get update -qq
            sudo apt-get install -y -qq libportaudio2
        fi
    elif command -v dnf >/dev/null 2>&1; then
        # Fedora/RHEL
        if rpm -q portaudio >/dev/null 2>&1; then
            info "portaudio already installed, skipping."
        else
            info "Installing portaudio via dnf..."
            sudo dnf install -y portaudio
        fi
    elif command -v yum >/dev/null 2>&1; then
        # Older RHEL/CentOS
        if rpm -q portaudio >/dev/null 2>&1; then
            info "portaudio already installed, skipping."
        else
            info "Installing portaudio via yum..."
            sudo yum install -y portaudio
        fi
    else
        warn "Cannot detect package manager (apt/dnf/yum). Please install portaudio manually."
    fi
}

# --- uv installation ---

install_uv() {
    if command -v uv >/dev/null 2>&1; then
        info "uv already installed: $(uv --version)"
        return
    fi

    info "Installing uv..."
    curl -fsSL "$UV_INSTALL_URL" | sh

    # Source the env file that uv's installer creates
    if [ -f "$HOME/.local/bin/env" ]; then
        # shellcheck source=/dev/null
        . "$HOME/.local/bin/env"
    elif [ -f "$HOME/.cargo/env" ]; then
        # shellcheck source=/dev/null
        . "$HOME/.cargo/env"
    fi

    # Add to PATH for this session if not already there
    if ! command -v uv >/dev/null 2>&1; then
        export PATH="$HOME/.local/bin:$PATH"
    fi

    if ! command -v uv >/dev/null 2>&1; then
        error "uv installation failed. Please install manually: https://docs.astral.sh/uv/"
    fi

    info "uv installed: $(uv --version)"
}

# --- s-peach installation ---

install_speach() {
    local install_arg="$PACKAGE"
    local extra_flags=()

    if [ "${WITH_CHATTERBOX:-}" = "1" ]; then
        install_arg="${PACKAGE}[chatterbox]"
        local overrides_file
        overrides_file="$(mktemp)"
        echo "$CHATTERBOX_OVERRIDES" > "$overrides_file"
        extra_flags=(--overrides "$overrides_file")
        info "Including chatterbox voice cloning support"
    fi

    if uv tool list 2>/dev/null | grep -q "^s-peach-tts "; then
        info "s-peach-tts already installed, upgrading..."
        uv tool upgrade "$PACKAGE" "${extra_flags[@]}" \
            || warn "Upgrade failed, try: uv tool install --force ${PACKAGE}"
    else
        info "Installing s-peach-tts..."
        uv tool install "$install_arg" "${extra_flags[@]}"
    fi
}

# --- Main ---

main() {
    info "s-peach installer"
    echo ""

    OS="$(detect_os)"
    info "Detected OS: ${OS}"

    # Step 1: System dependencies
    case "$OS" in
        macos)
            info "No system dependencies needed on macOS (sounddevice bundles portaudio)."
            ;;
        linux)
            install_linux_deps
            ;;
    esac

    # Step 2: Install uv
    install_uv

    # Step 3: Install s-peach
    install_speach

    # Step 4: Initialize config (non-interactive)
    info "Initializing config..."
    s-peach init --defaults

    # Step 5: Smoke test
    info "Verifying installation..."
    s-peach --version

    # Step 6: Success message
    echo ""
    info "Installation complete!"
    echo ""
    echo "  Quick start:"
    echo "    s-peach start              # Start the server"
    echo "    s-peach say 'hello world'  # Speak something"
    echo "    s-peach install-service    # Auto-start on login"
    echo ""
    echo "  More commands:"
    echo "    s-peach --help             # See all commands"
    echo "    s-peach config server      # Edit server config"
    echo ""
}

main "$@"
