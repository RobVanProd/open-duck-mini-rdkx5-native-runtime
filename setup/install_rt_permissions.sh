#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 2
fi

group="open-duck-rt"
user="${SUDO_USER:-${USER}}"
getent group "${group}" >/dev/null || groupadd --system "${group}"
usermod -a -G "${group}" "${user}"

install -m 0644 /dev/stdin /etc/security/limits.d/90-open-duck-rt.conf <<'EOF'
@open-duck-rt  -  rtprio   90
@open-duck-rt  -  memlock  unlimited
@open-duck-rt  -  nice     -10
EOF

echo "Installed RT limits for group ${group}. Log out/in before verification."
echo "Prefer the reviewed systemd unit for production CAP_SYS_NICE and CPUAffinity."
