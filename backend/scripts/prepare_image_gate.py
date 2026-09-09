"""Download official pinned CLIP weights once; export safetensors for offline serving."""
from pathlib import Path
import argparse

from transformers import CLIPModel, CLIPProcessor

REPOSITORY = "openai/clip-vit-base-patch32"
REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "models/image_gate")
    args = parser.parse_args()
    processor = CLIPProcessor.from_pretrained(REPOSITORY, revision=REVISION, use_fast=False)
    # Transformers requires torch >= 2.6 to safely load this official .bin checkpoint.
    model = CLIPModel.from_pretrained(REPOSITORY, revision=REVISION, use_safetensors=False)
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output, safe_serialization=True)
    processor.save_pretrained(args.output)
    (args.output / "SOURCE.txt").write_text(f"{REPOSITORY}\n{REVISION}\n", encoding="utf-8")
    print(f"Image gate ready: {args.output.resolve()}")


if __name__ == "__main__":
    main()
