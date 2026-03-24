"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: openai_client.py
@Time: 10/16/25; 9:18 AM
"""
from django.conf import settings
from openai import OpenAI
import base64
import json
import time

client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=20)


def chat(messages, model=None, temperature=0.2):
    model = model or settings.OPENAI_CHAT_MODEL
    print(f"[DEBUG] 🔹 Chat request -> model={model}, len(messages)={len(messages)}")
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=messages,
        )
        print(f"[DEBUG] ✅ LLM done in {time.time()-t0:.2f}s")
        return r.choices[0].message.content
    except Exception as e:
        print(f"[ERROR] ❌ LLM call failed after {time.time()-t0:.1f}s: {e}")
        return '{"query_type":"fact","entities":[],"relation":null,"confidence":0}'


def embed(texts, model=None, max_retries=3):
    """
    Create embeddings from text(s).
    Automatically handles dict inputs by converting to JSON strings.
    Supports string, list[str], or dict.
    """
    model = model or settings.OPENAI_EMBED_MODEL

    # --- Normalize input ---
    if isinstance(texts, dict):
        texts = [json.dumps(texts, ensure_ascii=False)]
    elif isinstance(texts, str):
        texts = [texts]
    elif isinstance(texts, list):
        texts = [
            json.dumps(t, ensure_ascii=False) if isinstance(t, dict) else str(t)
            for t in texts
        ]
    else:
        raise ValueError(f"[ERROR] Invalid input type for embedding: {type(texts)}")

    for attempt in range(1, max_retries + 1):
        try:
            r = client.embeddings.create(model=model, input=texts)
            return [d.embedding for d in r.data]
        except Exception as e:
            print(f"[ERROR] ❌ Embedding failed (attempt {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                raise
            time.sleep(2)


def vision_describe(image_bytes, prompt, model=None, max_output_tokens=300, max_retries=3):
    """Call a vision-enabled model using the Chat Completions API and return its textual output."""
    if not image_bytes:
        return ""

    model = model or getattr(settings, "OPENAI_VISION_MODEL", None) or "gpt-4o"
    encoded = base64.b64encode(image_bytes).decode("utf-8")

    # Detect MIME type from image bytes header
    mime_type = "image/jpeg"  # default
    if image_bytes[:4] == b'\x89PNG':
        mime_type = "image/png"
    elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        mime_type = "image/webp"
    elif image_bytes[:3] == b'GIF':
        mime_type = "image/gif"

    data_url = f"data:{mime_type};base64,{encoded}"

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_output_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                        ],
                    }
                ],
            )
            text = response.choices[0].message.content
            if text:
                return text.strip()
            return ""
        except Exception as e:
            print(f"[ERROR] ❌ Vision call failed (attempt {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                raise
            time.sleep(2)