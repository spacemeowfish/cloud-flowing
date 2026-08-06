"""Generate RKLLM calibration pairs using the production structured prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from agent_platform.adapters.structured_response import build_structured_system_prompt, flatten_rkllm_prompt
from agent_platform.models import INTENT_RESPONSE_SCHEMA, MessageRole, ModelMessage


EXPECTED_CATEGORIES = {
    "file_open",
    "knowledge_query",
    "meeting_process",
    "reminder_create",
    "todo_manage",
    "schedule_manage",
    "text_polish",
}


def load_seed_prompts(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("calibration prompt file must contain a non-empty list")
    prompts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"id", "category", "input"}:
            raise ValueError("each calibration prompt must contain only id, category, and input")
        normalized = {key: str(value).strip() for key, value in item.items()}
        if not all(normalized.values()):
            raise ValueError("calibration prompt fields cannot be empty")
        if normalized["id"] in seen:
            raise ValueError(f"duplicate calibration prompt id: {normalized['id']}")
        if normalized["category"] not in EXPECTED_CATEGORIES:
            raise ValueError(f"unsupported calibration category: {normalized['category']}")
        seen.add(normalized["id"])
        prompts.append(normalized)
    counts = Counter(item["category"] for item in prompts)
    missing = sorted(category for category in EXPECTED_CATEGORIES if counts[category] < 3)
    if missing:
        raise ValueError(f"calibration categories require at least three prompts: {', '.join(missing)}")
    return prompts


def rendered_prompts(seeds: list[dict[str, str]]) -> list[tuple[dict[str, str], str]]:
    system_prompt = build_structured_system_prompt(INTENT_RESPONSE_SCHEMA)
    return [
        (
            seed,
            flatten_rkllm_prompt(
                system_prompt,
                [ModelMessage(role=MessageRole.USER, content=seed["input"])],
            ),
        )
        for seed in seeds
    ]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    default_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--prompts", type=Path, default=default_root / "calibration_prompts.json")
    parser.add_argument("--output", type=Path, default=default_root / "data_quant.json")
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    seeds = load_seed_prompts(args.prompts)
    prompts = rendered_prompts(seeds)
    if args.validate_only:
        print(json.dumps({"prompts": len(prompts), "sha256": file_sha256(args.prompts)}, indent=2))
        return
    if args.model_dir is None:
        parser.error("--model-dir is required unless --validate-only is used")

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit("Install torch and transformers in the model-conversion environment") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(args.model_dir, trust_remote_code=True).to(device).eval()
    calibration: list[dict[str, str]] = []
    for seed, prompt in prompts:
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                repetition_penalty=1.0,
            )
        prompt_token_count = inputs["input_ids"].shape[-1]
        target = tokenizer.decode(outputs[0][prompt_token_count:], skip_special_tokens=True)
        calibration.append({"input": prompt, "target": target, "source_id": seed["id"]})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(calibration), "output": str(args.output), "sha256": file_sha256(args.output)}, indent=2))


if __name__ == "__main__":
    main()


__all__ = ["EXPECTED_CATEGORIES", "file_sha256", "load_seed_prompts", "rendered_prompts"]
