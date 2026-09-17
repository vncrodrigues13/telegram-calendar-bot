#!/usr/bin/env bash
#
# Prepares a fresh Oracle Cloud VM to run the bot: installs Docker Engine plus
# the compose plugin, enables it at boot, and creates the secrets directory.
#
# Works on both images OCI offers, because the console defaults to Oracle Linux
# (dnf, user "opc") while our plan calls for Ubuntu (apt, user "ubuntu") -- the
# usual reason "apt doesn't work" on a freshly created instance.
#
# Idempotent: safe to re-run.
#
#   curl -fsSL -o setup-vm.sh <raw-url> && bash setup-vm.sh
#   # or: scp deploy/setup-vm.sh <host>:~ && ssh <host> bash setup-vm.sh
#
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/eventbot}"
DATA_DIR="$APP_DIR/data"

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] && die "Run as the normal VM user (opc/ubuntu), not root -- the script uses sudo where needed."
command -v sudo >/dev/null || die "sudo not found."

# --- identify the platform -------------------------------------------------

[[ -r /etc/os-release ]] || die "Cannot read /etc/os-release; unsupported image."
# shellcheck disable=SC1091
. /etc/os-release

ARCH="$(uname -m)"
log "Detected ${PRETTY_NAME:-$ID $VERSION_ID} on ${ARCH}, user '${USER}'"

if [[ "$ARCH" != "aarch64" ]]; then
  warn "Expected aarch64 (Ampere A1). On ${ARCH}, an image built on an Apple Silicon"
  warn "Mac will not run here. Verify the instance shape is VM.Standard.A1.Flex."
fi

case "${ID}${ID_LIKE:+ $ID_LIKE}" in
  *ubuntu*|*debian*) FAMILY=debian ;;
  *ol*|*rhel*|*fedora*|*centos*) FAMILY=rhel ;;
  *) die "Unsupported distro '${ID}'. Expected Ubuntu or Oracle Linux." ;;
esac

# --- install Docker --------------------------------------------------------

install_debian() {
  # DPkg::Lock::Timeout waits out unattended-upgrades, which holds the dpkg
  # lock on a freshly booted VM and is the other common "apt is broken".
  local APT=(sudo apt-get -o DPkg::Lock::Timeout=600 -y)

  log "Installing prerequisites (apt)"
  "${APT[@]}" update
  "${APT[@]}" install ca-certificates curl git

  log "Adding Docker's apt repository"
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

  log "Installing Docker Engine"
  "${APT[@]}" update
  "${APT[@]}" install docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
}

install_rhel() {
  log "Installing prerequisites (dnf)"
  sudo dnf install -y dnf-plugins-core git

  log "Adding Docker's dnf repository"
  # Oracle Linux is RHEL-compatible, so the CentOS repo is the correct one.
  sudo dnf config-manager --add-repo \
    https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || true

  log "Installing Docker Engine"
  # Oracle Linux ships podman and its own runc, which conflict with
  # containerd.io; --allowerasing lets dnf replace them.
  sudo dnf install -y --allowerasing docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
}

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  log "Docker and the compose plugin are already installed -- skipping install"
else
  if [[ "$FAMILY" == debian ]]; then
    install_debian
  else
    install_rhel
  fi
fi

# --- enable at boot --------------------------------------------------------

# This is what makes the bot survive reboots and Oracle's idle-reclamation
# stop/start cycle: together with `restart: unless-stopped` in the compose
# file, recovery is just pressing Start in the console.
log "Enabling Docker at boot"
sudo systemctl enable --now docker

log "Adding '${USER}' to the docker group"
sudo usermod -aG docker "$USER"

# --- application directory -------------------------------------------------

log "Creating ${DATA_DIR}"
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

# --- verify ----------------------------------------------------------------

# sudo here because the new group membership is not active in this shell yet.
log "Verifying the Docker installation"
sudo docker run --rm hello-world >/dev/null \
  && echo "    docker: OK" \
  || die "Docker installed but cannot run containers."

sudo docker compose version | sed 's/^/    /'

cat <<EOF

$(log "Done")

Docker $(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,) is installed
and enabled at boot. Data directory: ${DATA_DIR}

IMPORTANT: log out and back in before running docker without sudo --
the 'docker' group membership does not apply to this session.

    exit
    ssh <this-host>

Next steps, from your Mac:

    scp .env token.json <this-host>:${DATA_DIR}/
    ssh <this-host> 'chmod 600 ${DATA_DIR}/.env ${DATA_DIR}/token.json'

Then on the VM:

    git clone <repo-url> ${APP_DIR}/app && cd ${APP_DIR}/app
    docker compose up -d --build
    docker compose logs -f

Note: credentials.json is deliberately NOT copied to the VM -- token.json
already carries the refresh token. See specs/plans/oracle-free-tier-deploy/plan.md
EOF
