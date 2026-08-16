#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 qwen|lfm IMAGE_TAR [--skip-pressure]" >&2
    exit 2
fi
model="$1"
archive="$2"
pressure_argument="${3:-}"
bind_address="${POC_BIND_ADDRESS:-127.0.0.1}"
developer_password="${DEVELOPER_PASSWORD:-${POC_DEVELOPER_PASSWORD:-}}"
[ -n "$developer_password" ] || { echo "DEVELOPER_PASSWORD or POC_DEVELOPER_PASSWORD is required" >&2; exit 2; }
case "$model" in
    qwen) image="cloud-flowing-qwen2.5-3b:rk3588-cpu-poc" ;;
    lfm) image="cloud-flowing-lfm2.5-1.2b:rk3588-cpu-poc" ;;
    *) echo "Unknown model: $model" >&2; exit 2 ;;
esac

architecture="$(uname -m)"
case "$architecture" in
    aarch64|arm64) ;;
    *) echo "This package is for ARM64; detected $architecture" >&2; exit 2 ;;
esac
command -v docker >/dev/null 2>&1 || { echo "Docker is required" >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is not available" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required for the automatic board benchmark" >&2; exit 2; }
[ -r "$archive" ] || { echo "Image archive is not readable: $archive" >&2; exit 2; }

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
checksum_file="$script_dir/SHA256SUMS"
if [ -r "$checksum_file" ]; then
    command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required to verify the image archive" >&2; exit 2; }
    archive_name="$(basename -- "$archive")"
    expected_checksum="$(awk -v name="$archive_name" '$2 == name { print $1 }' "$checksum_file")"
    [ -n "$expected_checksum" ] || { echo "No checksum entry for $archive_name" >&2; exit 2; }
    actual_checksum="$(sha256sum "$archive" | awk '{ print $1 }')"
    [ "$actual_checksum" = "$expected_checksum" ] || { echo "SHA256 mismatch for $archive_name" >&2; exit 2; }
fi
results_dir="${PWD}/rk3588-results-${model}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$results_dir"
sh "$script_dir/board_probe.sh" "$results_dir/board-probe.txt"
docker load --input "$archive"

set -- python3 "$script_dir/benchmark_profiles.py" --image "$image" --output "$results_dir" --bind-address "$bind_address"
if [ "$pressure_argument" = "--skip-pressure" ]; then
    set -- "$@" --skip-pressure
fi
DEVELOPER_PASSWORD="$developer_password" "$@"
echo "Agent URL: http://$bind_address:8000"
echo "Selected configuration: $results_dir/selected.env"
echo "Acceptance evidence: $results_dir/benchmark-report.json"
