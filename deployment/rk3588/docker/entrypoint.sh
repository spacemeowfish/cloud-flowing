#!/bin/sh
set -eu

require_positive_integer() {
    name="$1"
    value="$2"
    case "$value" in
        ''|0|*[!0-9]*)
        echo "$name must be a positive integer, got: $value" >&2
        exit 2
        ;;
    esac
}

require_positive_integer LLAMACPP_THREADS "$LLAMACPP_THREADS"
require_positive_integer LLAMACPP_CONTEXT_SIZE "$LLAMACPP_CONTEXT_SIZE"
require_positive_integer LLAMACPP_MAX_TOKENS "$LLAMACPP_MAX_TOKENS"
require_positive_integer LLAMACPP_BATCH_SIZE "$LLAMACPP_BATCH_SIZE"
require_positive_integer LLAMACPP_PARALLEL "$LLAMACPP_PARALLEL"

MODEL_PATH="${MODEL_PATH:-/opt/models/model.gguf}"
if [ ! -r "$MODEL_PATH" ]; then
    echo "Model is not readable: $MODEL_PATH" >&2
    exit 2
fi

export MODEL_NAME="${LLAMACPP_MODEL_NAME}"
export MODEL_DIGEST="${LLAMACPP_MODEL_DIGEST:-unknown}"

/usr/local/bin/llama-server \
    --model "$MODEL_PATH" \
    --host 127.0.0.1 \
    --port 8080 \
    --threads "$LLAMACPP_THREADS" \
    --ctx-size "$LLAMACPP_CONTEXT_SIZE" \
    --batch-size "$LLAMACPP_BATCH_SIZE" \
    --parallel "$LLAMACPP_PARALLEL" \
    --jinja &
model_pid=$!

terminate() {
    trap - TERM INT EXIT
    if [ -n "${agent_pid:-}" ]; then
        kill -TERM "$agent_pid" 2>/dev/null || true
        wait "$agent_pid" 2>/dev/null || true
    fi
    kill -TERM "$model_pid" 2>/dev/null || true
    wait "$model_pid" 2>/dev/null || true
}
trap terminate TERM INT EXIT

attempt=0
while [ "$attempt" -lt 360 ]; do
    if ! kill -0 "$model_pid" 2>/dev/null; then
        wait "$model_pid"
        exit 1
    fi
    if curl --silent --fail --max-time 2 http://127.0.0.1:8080/health >/dev/null; then
        break
    fi
    sleep 1
    attempt=$((attempt + 1))
done
if ! curl --silent --fail --max-time 2 http://127.0.0.1:8080/health >/dev/null; then
    echo "llama.cpp did not become healthy within 360 seconds" >&2
    exit 1
fi

python -m agent_platform.cli serve &
agent_pid=$!
while kill -0 "$model_pid" 2>/dev/null && kill -0 "$agent_pid" 2>/dev/null; do
    sleep 1
done
set +e
if ! kill -0 "$model_pid" 2>/dev/null; then
    wait "$model_pid"
    status=$?
else
    wait "$agent_pid"
    status=$?
fi
exit "$status"
