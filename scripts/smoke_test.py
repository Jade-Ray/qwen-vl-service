import argparse
import base64
import json
import os
from pathlib import Path

import httpx
from openai import OpenAI


def load_image_base64(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def run_echo(endpoint: str, image_path: Path, service_key: str | None) -> None:
    headers = {"X-API-Key": service_key} if service_key else {}
    payload = {"image_base64": load_image_base64(image_path)}
    response = httpx.post(f"{endpoint.rstrip('/')}/v1/debug/echo-image", json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()
    print(json.dumps({"status": "ok", "image_width": data["image_width"], "image_height": data["image_height"]}, ensure_ascii=False, indent=2))


def run_detect(endpoint: str, image_path: Path, prompt: str | None, service_key: str | None) -> None:
    headers = {"X-API-Key": service_key} if service_key else {}
    payload: dict = {"image_base64": load_image_base64(image_path)}
    if prompt:
        payload["prompt"] = prompt
    response = httpx.post(f"{endpoint.rstrip('/')}/v1/detect", json=payload, headers=headers, timeout=180)
    response.raise_for_status()
    data = response.json()
    if data["type"] == "detected":
        print(json.dumps(data["objects"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"type": "no_detection"}, ensure_ascii=False, indent=2))


def run_qwen(image_path: Path, prompt: str, api_key: str, base_url: str, model: str) -> None:
    client = OpenAI(api_key=api_key, base_url=base_url)
    image_base64 = load_image_base64(image_path)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=512,
        temperature=0,
    )
    print(response.choices[0].message.content)


def run_qwen_text(prompt: str, api_key: str, base_url: str, model: str) -> None:
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0,
    )
    print(response.choices[0].message.content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke tests for the Qwen-VL detection service.")
    parser.add_argument("mode", choices=["echo", "detect", "qwen", "text"])
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--image", default="images/test.png")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--api-key", default=os.getenv("QWEN_API_KEY"))
    parser.add_argument("--base-url", default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    parser.add_argument("--model", default="qwen-vl-max")
    parser.add_argument("--service-key", default=os.getenv("SERVICE_API_KEY"))
    args = parser.parse_args()

    if args.mode == "echo":
        image_path = Path(args.image)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        run_echo(args.endpoint, image_path, args.service_key)
        return

    if args.mode == "detect":
        image_path = Path(args.image)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        run_detect(args.endpoint, image_path, args.prompt, args.service_key)
        return

    if not args.api_key:
        raise RuntimeError("The qwen/text mode requires --api-key or QWEN_API_KEY.")

    if args.mode == "text":
        run_qwen_text(args.prompt, args.api_key, args.base_url, args.model)
        return

    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    run_qwen(image_path, args.prompt, args.api_key, args.base_url, args.model)


if __name__ == "__main__":
    main()
