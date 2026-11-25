"""How a post becomes model input: caption text, then the text read from its image."""


def model_input(post: dict) -> str:
    text = (post.get("text") or "").strip()
    ocr = (post.get("ocr_text") or "").strip()
    if ocr:
        return f"{text}\n[IMAGE TEXT] {ocr}" if text else f"[IMAGE TEXT] {ocr}"
    return text
