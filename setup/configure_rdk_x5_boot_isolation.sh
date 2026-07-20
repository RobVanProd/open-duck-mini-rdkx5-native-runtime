#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 [control-cpu]" >&2
  exit 2
fi

core="${1:-7}"
if ! [[ "${core}" =~ ^[0-9]+$ ]]; then
  echo "control CPU must be a nonnegative integer" >&2
  exit 2
fi
if [[ ! -d "/sys/devices/system/cpu/cpu${core}" ]]; then
  echo "control CPU ${core} does not exist" >&2
  exit 2
fi

boot_cmd="/boot/boot.cmd"
boot_scr="/boot/boot.scr"
backup_cmd="/boot/boot.cmd.pre-open-duck-rt"
backup_scr="/boot/boot.scr.pre-open-duck-rt"
arguments="isolcpus=${core}"

for required in "${boot_cmd}" "${boot_scr}"; do
  if [[ ! -f "${required}" ]]; then
    echo "required boot file is missing: ${required}" >&2
    exit 2
  fi
done
if ! command -v mkimage >/dev/null 2>&1; then
  echo "mkimage is required to rebuild ${boot_scr}" >&2
  exit 2
fi
if [[ "$(grep -c '^setenv bootargs ' "${boot_cmd}")" -ne 1 ]]; then
  echo "expected exactly one setenv bootargs line in ${boot_cmd}" >&2
  exit 2
fi

if grep -Eq '(^| )isolcpus=' "${boot_cmd}"; then
  if ! grep -Fq "isolcpus=${core}" "${boot_cmd}"; then
    echo "boot.cmd already contains a different isolation configuration" >&2
    exit 2
  fi
  echo "boot.cmd already contains isolcpus=${core}; rebuilding boot.scr"
elif grep -Eq '(^| )(nohz_full|rcu_nocbs)=' "${boot_cmd}"; then
  echo "boot.cmd contains tickless/RCU arguments without isolcpus; review manually" >&2
  exit 2
else
  if [[ -e "${backup_cmd}" || -e "${backup_scr}" ]]; then
    if [[ ! -f "${backup_cmd}" || ! -f "${backup_scr}" ]] \
      || ! cmp -s "${backup_cmd}" "${boot_cmd}" \
      || ! cmp -s "${backup_scr}" "${boot_scr}"; then
      echo "refusing to overwrite incomplete or nonmatching Open Duck boot backups" >&2
      exit 2
    fi
    echo "reusing matching backups from an earlier staged attempt"
  else
    cp -a "${boot_cmd}" "${backup_cmd}"
    cp -a "${boot_scr}" "${backup_scr}"
  fi
fi

tmp_cmd="$(mktemp /boot/boot.cmd.open-duck-rt.XXXXXX)"
tmp_scr="$(mktemp /boot/boot.scr.open-duck-rt.XXXXXX)"
cleanup() {
  rm -f "${tmp_cmd}" "${tmp_scr}"
}
trap cleanup EXIT

if grep -Fq "${arguments}" "${boot_cmd}"; then
  # The stock 6.1.83 X5 kernel reports CONFIG_NO_HZ_FULL unsupported and
  # rcu_nocbs unknown. Remove those inert arguments if an earlier staged
  # configuration included them, while retaining the proven isolcpus setting.
  sed -E 's/ nohz_full=[^ " ]+//g; s/ rcu_nocbs=[^ " ]+//g' \
    "${boot_cmd}" > "${tmp_cmd}"
else
  sed '/^setenv bootargs / s/"$/ '"${arguments}"'"/' \
    "${boot_cmd}" > "${tmp_cmd}"
fi
if ! grep -Fq "${arguments}" "${tmp_cmd}"; then
  echo "failed to place isolation arguments in staged boot.cmd" >&2
  exit 2
fi

mkimage -C none -A arm -T script -d "${tmp_cmd}" "${tmp_scr}"
install -o root -g root -m 0755 "${tmp_cmd}" "${boot_cmd}"
install -o root -g root -m 0644 "${tmp_scr}" "${boot_scr}"
sync

echo "configured_arguments=${arguments}"
sha256sum "${backup_cmd}" "${backup_scr}" "${boot_cmd}" "${boot_scr}"
echo "rollback: sudo install -m 0755 ${backup_cmd} ${boot_cmd} && sudo install -m 0644 ${backup_scr} ${boot_scr}"
echo "Reboot is required. Verify /proc/cmdline and /sys/devices/system/cpu/isolated afterward."
