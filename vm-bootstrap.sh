#!/usr/bin/env bash
# Prepare a Linux VM for the evm.fast `lean` track, fail-closed.
# Usage: YUKON_API_TOKEN=... bash vm-bootstrap.sh [workdir]
# The token is read from the environment only; it never appears in argv or shell history.
set -euo pipefail

WORK="${1:-$HOME/evm-fast}"
CHALLENGE=6233fccb-45f5-4d4f-a089-fa870a631b7e
# Hash of the install.sh audited on 2026-11-03. A different hash stops the bootstrap.
INSTALLER_SHA256=f857bc2a266fe49aefaa2f29ec76f09aad128a415f0876e8bba385bc83106ef0

fail() { printf 'bootstrap: %s\n' "$1" >&2; exit 1; }
say() { printf '== %s\n' "$1"; }

say "host requirements"
[ "$(uname -s)" = Linux ] || fail "Linux required"
systemd_version=$(systemctl --version | awk 'NR==1 {print $2}')
[ "${systemd_version%%.*}" -ge 257 ] || fail "systemd $systemd_version < 257"
grep -qw landlock /sys/kernel/security/lsm || fail "Landlock is not an active LSM"
mem_gib=$(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo)
[ "$mem_gib" -ge 100 ] || printf 'warning: %s GiB RAM; official units may use up to 112 GiB\n' "$mem_gib" >&2
mkdir -p "$(dirname "$WORK")"
free_gib=$(df -BG --output=avail "$(dirname "$WORK")" | tail -1 | tr -dc 0-9)
[ "$free_gib" -ge 200 ] || fail "${free_gib} GiB free; the build writes about 120 GB"
probe=$(mktemp -d "$(dirname "$WORK")/case.XXXX")
touch "$probe/a" "$probe/A"
[ "$(ls "$probe" | wc -l)" -eq 2 ] || fail "file system is case-insensitive"
rm -rf "$probe"

say "packages"
sudo apt-get update -qq
sudo apt-get install -y -qq build-essential git curl unzip python3 golang-go tmux
if ! command -v cargo >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
fi
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$HOME/.bun/bin:$HOME/.elan/bin:$PATH"

say "yukon CLI (audited installer only)"
installer=$(mktemp)
curl -fsSL https://api.yukon.org/yukon/install.sh -o "$installer"
echo "$INSTALLER_SHA256  $installer" | sha256sum -c --quiet - \
  || fail "install.sh changed since the audit; read it and update INSTALLER_SHA256"
YUKON_INSTALL_SKILL=0 sh "$installer"
rm -f "$installer"

# Turn collection off before any command that could sync a transcript.
yukon trace off
yukon config --telemetry disabled
yukon automining notify off
[ -n "${YUKON_API_TOKEN:-}" ] || fail "set YUKON_API_TOKEN in the environment"
yukon trace status | grep -q 'Trace collection *disabled' || fail "trace collection still enabled"

say "clone"
[ -e "$WORK" ] && fail "$WORK already exists"
(cd "$(dirname "$WORK")" && yukon clone "$CHALLENGE" "$(basename "$WORK")")
git -C "$WORK" rev-parse HEAD > "$WORK.base-commit"

say "setup (long; log in $WORK.setup.log)"
cd "$WORK"
tmux new-session -d -s evm-fast-setup \
  "yukon setup --track lean > '$WORK.setup.log' 2>&1; echo exit=\$? >> '$WORK.setup.log'"
say "attach with: tmux attach -t evm-fast-setup"
