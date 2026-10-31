
echo "PROBE_OK=1"
echo "HOSTNAME=$(hostname 2>/dev/null)"
if command -v sw_vers >/dev/null 2>&1; then
  echo "OS_NAME=macOS $(sw_vers -productVersion 2>/dev/null)"
  echo "ARCH=$(uname -m 2>/dev/null)"
  echo "CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
  echo "MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null)"
  echo "LOADAVG=$(sysctl -n vm.loadavg 2>/dev/null)"
  echo "BOOT_EPOCH=$(sysctl -n kern.boottime 2>/dev/null | awk '{print $4}')"
  echo "UPTIME_SECS="
  echo "CPU_LINE=$(top -l 2 -n 0 2>/dev/null | grep 'CPU usage' | tail -1)"
  echo "GPU_UTIL=$(ioreg -r -d 1 -w 0 -c IOAccelerator 2>/dev/null | grep -m1 'Device Utilization')"
  echo "VMSTAT=$(vm_stat 2>/dev/null | grep -E 'Pages free|Pages speculative' | tr '\n' ';')"
  echo "SWAP=$(sysctl -n vm.swapusage 2>/dev/null)"
  echo "NET_B=$(netstat -ib 2>/dev/null | awk '$3 ~ /^<Link/ {rx+=$7; tx+=$10} END {print rx+0, tx+0}')"
  echo "POWER_JSON=$(cat /usr/local/var/wcc-metrics/power.json 2>/dev/null)"
  bdest="$(tmutil destinationinfo 2>/dev/null | awk '/^Name/ {sub(/^[^:]*:[[:space:]]*/, ""); print; exit}' | tr -d '\042\134')"
  brunning="false"; pgrep -xq backupd 2>/dev/null && brunning="true"
  blatest="$(tmutil latestbackup 2>/dev/null | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}-[0-9]\{6\}' | tail -1)"
  bepoch="$(date -j -f '%Y-%m-%d-%H%M%S' "$blatest" '+%s' 2>/dev/null)"
  echo "BACKUP_JSON={\"schema\": 1, \"configured\": $([ -n "$bdest" ] && echo true || echo false), \"latestEpoch\": ${bepoch:-null}, \"running\": $brunning, \"dest\": \"$bdest\"}"
else
  echo "OS_NAME=Linux $(uname -r 2>/dev/null)"
  echo "ARCH=$(uname -m 2>/dev/null)"
  echo "CHIP=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//')"
  echo "MEM_BYTES=$(awk '/^MemTotal:/{print $2*1024}' /proc/meminfo 2>/dev/null)"
  echo "LOADAVG=$(cat /proc/loadavg 2>/dev/null)"
  echo "BOOT_EPOCH="
  echo "UPTIME_SECS=$(awk '{print int($1)}' /proc/uptime 2>/dev/null)"
  echo "CPU_A=$(awk '/^cpu /{print $2+$3+$4, $5}' /proc/stat 2>/dev/null)"
  sleep 1
  echo "CPU_B=$(awk '/^cpu /{print $2+$3+$4, $5}' /proc/stat 2>/dev/null)"
  echo "GPU_UTIL=$(cat /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1)"
  echo "MEM_AVAIL=$(awk '/^MemAvailable:/{print $2*1024}' /proc/meminfo 2>/dev/null)"
  echo "SWAP=$(awk '/^SwapTotal:/{t=$2} /^SwapFree:/{f=$2} END{print t*1024, f*1024}' /proc/meminfo 2>/dev/null)"
  echo "NET_B=$(grep -v '^ *lo:' /proc/net/dev 2>/dev/null | awk '{rx+=$2; tx+=$10} END {print rx+0, tx+0}')"
fi
echo "DISK_K=$(df -k / 2>/dev/null | awk 'END{print $2, $3, $4}')"

# Only explicitly selected service labels, never arguments, logs or processes.
for fleet_service in ${FLEET_SERVICES:-}; do
  if command -v sw_vers >/dev/null 2>&1; then
    fleet_state=$(launchctl print "gui/$(id -u)/$fleet_service" 2>/dev/null | awk '/state = / {print $3; exit}')
  elif command -v systemctl >/dev/null 2>&1; then
    fleet_state=$(systemctl show --property=ActiveState --value "$fleet_service" 2>/dev/null)
  fi
  case "$fleet_state" in running|active|inactive|failed|waiting|exited) ;; *) fleet_state=unverified ;; esac
  echo "SERVICE_$fleet_service=$fleet_state"
  fleet_state=
done

# Mounted local block volumes only; APFS volumes may share capacity.
echo "VOLUMES_K=$(df -klP 2>/dev/null | awk '$1 ~ /^\/dev\// && $2 ~ /^[0-9]+$/ {mount=$6; for(i=7;i<=NF;i++)mount=mount " " $i; print $1 "|" mount "|" $2 "|" $3 "|" $4}' | tr '\n' ';')"
if [ -r /proc/diskstats ]; then
  echo "IO_B=$(awk '$3 ~ /^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$/ {r+=$6;w+=$10;n++} END{if(n)printf "%.0f %.0f",r*512,w*512}' /proc/diskstats)"
else
  fleet_io=$(ioreg -r -c IOBlockStorageDriver -l 2>/dev/null)
  fleet_read=$(printf '%s' "$fleet_io" | sed -n 's/.*"Bytes (Read)"=\([0-9][0-9]*\).*/\1/p' | awk '{sum+=$1;n++} END{if(n)printf "%.0f",sum}')
  fleet_write=$(printf '%s' "$fleet_io" | sed -n 's/.*"Bytes (Write)"=\([0-9][0-9]*\).*/\1/p' | awk '{sum+=$1;n++} END{if(n)printf "%.0f",sum}')
  echo "IO_B=$fleet_read $fleet_write"
fi
