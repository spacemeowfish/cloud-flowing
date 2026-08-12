#!/bin/sh
set -eu

model="${1:-all}"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_dir/../../.." && pwd)"
output_dir="${2:-$repository_root/dist/rk3588}"
mkdir -p "$output_dir"

build_one() {
    name="$1"
    values="$(python3 - "$script_dir/models.lock.json" "$name" <<'PY'
import json, sys
spec = json.load(open(sys.argv[1], encoding='utf-8'))[sys.argv[2]]
print(spec['filename'])
print(spec['sha256'])
print(spec['image'])
PY
)"
    filename="$(printf '%s\n' "$values" | sed -n '1p')"
    digest="$(printf '%s\n' "$values" | sed -n '2p')"
    image="$(printf '%s\n' "$values" | sed -n '3p')"
    model_path="$repository_root/models/$filename"
    [ -r "$model_path" ] || { echo "Missing model: $model_path" >&2; exit 2; }
    printf '%s  %s\n' "$digest" "$model_path" | sha256sum --check --status
    docker buildx build \
        --platform linux/arm64 \
        --file "$script_dir/Dockerfile.cpu-poc" \
        --tag "$image" \
        --build-arg "MODEL_FILE=$filename" \
        --build-arg "MODEL_NAME=$name" \
        --build-arg "MODEL_SHA256=$digest" \
        --output "type=docker,dest=$output_dir/cloud-flowing-$name-rk3588-cpu-poc.tar" \
        "$repository_root"
}

case "$model" in
    qwen|lfm) build_one "$model" ;;
    all) build_one qwen; build_one lfm ;;
    *) echo "Usage: $0 qwen|lfm|all [OUTPUT_DIR]" >&2; exit 2 ;;
esac
cp "$script_dir/install.sh" "$script_dir/board_probe.sh" "$script_dir/benchmark_profiles.py" "$script_dir/README.md" "$output_dir/"
