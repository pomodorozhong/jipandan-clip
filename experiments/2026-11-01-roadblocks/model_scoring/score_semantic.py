"""Score local transcript rows with a pinned Liquid d1 checkpoint, without sending audio/text out.

Experimental only. Input JSON rows need unique ``id`` and ``text`` fields; labels are never
passed to the model. Download/review the model's custom code separately, then pass its local
folder. Outputs contain scores, text hashes, prompts, versions and runtime measurements.
Run in a disposable uv environment with transformers, torch, torchvision and pillow.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import resource
import threading
import time
from pathlib import Path

QUESTIONS = {
    "reusable": {"type": "noul", "instructions": (
        "Would this Mandarin gaming-stream transcript work as a short reusable soundboard "
        "reaction in everyday conversation? Favor expressive reactions, exclamations, jokes, "
        "greetings and clear standalone phrases. Disfavor game instructions, item/location "
        "names, descriptions of ongoing gameplay, filler and incomplete fragments. Judge "
        "only the given transcript; do not assume missing context or vocal delivery."
    )},
    "standalone": {"type": "noul", "instructions": (
        "Does this Mandarin utterance express a complete understandable reaction or message "
        "without seeing the game or hearing surrounding conversation?"
    )},
    "expressive": {"type": "noul", "instructions": (
        "Does the wording express a recognizable emotional reaction, joke, greeting or "
        "exclamation, rather than neutral narration or gameplay instructions?"
    )},
}


class MpsMemorySampler:
    """Sample driver allocation during inference; this is a lower bound on the true peak."""
    interval_seconds = .02

    def __init__(self, torch, enabled):
        self.peak_bytes = 0
        self.stopped = threading.Event()
        self.thread = None
        if enabled:
            def sample():
                while not self.stopped.wait(self.interval_seconds):
                    self.peak_bytes = max(self.peak_bytes, torch.mps.driver_allocated_memory())
            self.thread = threading.Thread(target=sample, daemon=True)
            self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--token-budget", type=int, default=8192)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--device", choices=["mps", "cpu", "cuda"], default="mps")
    parser.add_argument("--questions", type=Path, help="fixed question definitions saved before evaluation")
    parser.add_argument("--audio", action="store_true", help="attach each row's local audio_path")
    args = parser.parse_args()
    if args.batch_size <= 0 or args.token_budget <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error("batch size, token budget and limit must be positive")
    import torch
    from transformers import AutoModel

    rows = json.loads(args.input.read_text())
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("duplicate input row ids")
    if args.limit is not None:
        rows = rows[:args.limit]
    questions = json.loads(args.questions.read_text()) if args.questions else QUESTIONS
    if args.out.exists():
        raise ValueError("output already exists; use a new path")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    memory = MpsMemorySampler(torch, args.device == "mps")
    t0 = time.perf_counter()
    dtype = torch.float32 if args.device == "cpu" else torch.bfloat16
    model = AutoModel.from_pretrained(
        str(args.model.resolve()), trust_remote_code=True, local_files_only=True, dtype=dtype,
    ).to(args.device).eval()
    model.engine.token_budget = args.token_budget
    load_seconds = time.perf_counter() - t0
    print(json.dumps({"loaded_seconds": load_seconds, "rows": len(rows)}), flush=True)
    batches = []
    observed_mps_bytes = 0
    with args.out.open("w") as out, torch.inference_mode():
        for start in range(0, len(rows), args.batch_size):
            batch = rows[start:start + args.batch_size]
            t = time.perf_counter()
            answers = model.system_one_batch([
                ({"transcript": r["text"]}, questions,
                 [{"type": "audio", "path": r["audio_path"]}] if args.audio else []) for r in batch
            ])
            if args.device == "mps":
                torch.mps.synchronize()
                observed_mps_bytes = max(observed_mps_bytes, torch.mps.driver_allocated_memory())
            elapsed = time.perf_counter() - t
            batches.append(elapsed)
            for row, answer in zip(batch, answers, strict=True):
                out.write(json.dumps({
                    "id": row["id"], "text_sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                    "scores": {k: float(v["noul"]) for k, v in answer["answers"].items()},
                    "input_tokens": answer["usage"]["input_tokens"],
                    **({"audio_sha256": digest(Path(row["audio_path"]))} if args.audio else {}),
                }) + "\n")
            out.flush()
            if start == 0 or (start // args.batch_size) % 10 == 0:
                print(json.dumps({"done": start + len(batch), "batch_seconds": elapsed}), flush=True)
    memory.stop()
    stats = {
        "model_revision": args.revision, "input_sha256": digest(args.input),
        "checkpoint_sha256": digest(args.model / "model.safetensors"),
        "custom_code_sha256": {p.name: digest(p) for p in sorted(args.model.glob("*.py"))},
        "questions": questions, "audio": args.audio, "device": args.device, "dtype": str(dtype),
        "versions": {p: importlib.metadata.version(p) for p in ["torch", "transformers", "numpy"]},
        "python": platform.python_version(), "platform": platform.platform(),
        "rows": len(rows), "batch_size": args.batch_size, "token_budget": args.token_budget,
        "load_seconds": load_seconds,
        "batch_seconds": batches, "score_seconds": sum(batches),
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system() == "Darwin" else 1024),
        "mps_driver_bytes_at_end": torch.mps.driver_allocated_memory() if args.device == "mps" else None,
        "mps_tensor_bytes_at_end": torch.mps.current_allocated_memory() if args.device == "mps" else None,
        "mps_driver_bytes_max_observed_after_batch": observed_mps_bytes,
        "mps_driver_bytes_sampled_peak": memory.peak_bytes if args.device == "mps" else None,
        "mps_memory_sample_interval_seconds": memory.interval_seconds,
    }
    args.out.with_suffix(".manifest.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps({k: v for k, v in stats.items() if k in ["rows", "score_seconds", "peak_process_rss_bytes"]}), flush=True)


if __name__ == "__main__":
    main()
