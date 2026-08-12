#!/bin/sh
set -eu

output="${1:-rk3588-board-probe.txt}"
{
    echo "timestamp=$(date -Iseconds)"
    echo "architecture=$(uname -m)"
    echo "kernel=$(uname -srmo)"
    if [ -r /etc/os-release ]; then
        sed 's/^/os_/' /etc/os-release
    fi
    echo "glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
    echo "docker=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unavailable)"
    echo "docker_arch=$(docker info --format '{{.Architecture}}' 2>/dev/null || echo unavailable)"
    echo "cpu_online=$(cat /sys/devices/system/cpu/online 2>/dev/null || true)"
    echo "cpu_topology_begin"
    lscpu 2>/dev/null || true
    echo "cpu_topology_end"
    echo "memory_begin"
    free -h 2>/dev/null || cat /proc/meminfo
    echo "memory_end"
    echo "disk_begin"
    df -h . /var/lib/docker 2>/dev/null || df -h .
    echo "disk_end"
    for zone in /sys/class/thermal/thermal_zone*; do
        [ -r "$zone/temp" ] || continue
        echo "thermal_$(basename "$zone")=$(cat "$zone/temp")"
    done
} | tee "$output"
