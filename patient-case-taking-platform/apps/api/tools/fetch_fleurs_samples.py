"""Fetch a small labeled Hugging Face viewer sample for local ASR validation."""

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path


def _json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        return json.load(response)


def _audio_url(value: object) -> str:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return str(value[0]["src"])
    if isinstance(value, dict) and "src" in value:
        return str(value["src"])
    raise ValueError("Dataset viewer did not return a downloadable audio URL")


def fetch(
    output: Path,
    dataset: str,
    config: str,
    split: str,
    count: int,
    reference_field: str,
    language: str,
) -> Path:
    query = urllib.parse.urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": 0,
            "length": count,
        }
    )
    payload = _json(f"https://datasets-server.huggingface.co/rows?{query}")
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.jsonl"
    entries = []
    for index, item in enumerate(payload["rows"]):
        row = item["row"]
        audio_path = output / f"sample-{index:02d}.wav"
        urllib.request.urlretrieve(_audio_url(row["audio"]), audio_path)  # noqa: S310
        entries.append(
            {
                "audio": audio_path.name,
                "reference": row[reference_field],
                "language": language,
                "source": f"{dataset}:{config}:{split}:{item['row_idx']}",
            }
        )
    manifest.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset", default="google/fleurs")
    parser.add_argument("--config", default="en_us")
    parser.add_argument("--split", default="test")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--reference-field", default="transcription")
    parser.add_argument("--language", default="en")
    arguments = parser.parse_args()
    print(
        fetch(
            arguments.output,
            arguments.dataset,
            arguments.config,
            arguments.split,
            arguments.count,
            arguments.reference_field,
            arguments.language,
        )
    )
