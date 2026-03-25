import base64
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from section_0_basic_llm.prompt import build_system_prompt


DATA_DIR = Path(__file__).resolve().parent / "sample_data"
VECTOR_DB_PATH = DATA_DIR / "qa_vectors.json"


class ChatTurn(BaseModel):
    role: str
    text: str


class LLMConfig(BaseModel):
    model: str = "gpt-4o"
    system_prompt: str = "You are a helpful enterprise assistant."
    memory: bool = False
    memory_rounds: int = Field(default=4, ge=1, le=10)
    rag: bool = False
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)


class QAChunk(BaseModel):
    id: int
    question: str
    answer: str
    embedding: List[float]


class ChatResult(BaseModel):
    reply: str
    used_rag: bool = False
    reference_qa_id: Optional[int] = None



def _validate_image_data_url(image_data_url: str) -> None:
    match = re.match(r"^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$", image_data_url, re.DOTALL)
    if not match:
        raise RuntimeError("圖片格式錯誤，請重新上傳 PNG/JPEG/WebP。")

    mime = match.group(1).lower()
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise RuntimeError("目前只支援 PNG/JPEG/WebP，請先轉檔。")

    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("圖片內容損壞，請重新上傳。") from exc

    if len(raw) > 8 * 1024 * 1024:
        raise RuntimeError("圖片太大，請使用 8MB 以下圖片。")



def _load_env_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing in environment.")
    return OpenAI(api_key=api_key)



def _load_vector_db() -> List[QAChunk]:
    if not VECTOR_DB_PATH.exists():
        return []
    data = json.loads(VECTOR_DB_PATH.read_text(encoding="utf-8-sig"))
    return [QAChunk.model_validate(item) for item in data]



def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)



def _deterministic_embedding(text: str, dim: int = 64) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = list(digest) * ((dim // len(digest)) + 1)
    return [((seed[i] / 255.0) * 2.0) - 1.0 for i in range(dim)]



def _embed_text(client: OpenAI, text: str) -> List[float]:
    embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        response = client.embeddings.create(model=embedding_model, input=[text])
        return response.data[0].embedding
    except Exception:
        return _deterministic_embedding(text)



def _retrieve_top_qa(client: OpenAI, question: str) -> Tuple[Optional[dict], float]:
    vector_db = _load_vector_db()
    if not vector_db:
        return None, 0.0

    query_embedding = _embed_text(client, question)

    best_item = None
    best_score = -1.0
    for item in vector_db:
        score = _cosine_similarity(query_embedding, item.embedding)
        if score > best_score:
            best_score = score
            best_item = item

    if best_item is None:
        return None, 0.0

    return {
        "id": best_item.id,
        "question": best_item.question,
        "answer": best_item.answer,
    }, best_score



def _build_memory_messages(history: List[ChatTurn], user_message: str, rounds: int) -> List[dict]:
    turns = [item for item in history if item.role in {"user", "assistant"}]

    if turns and turns[-1].role == "user" and turns[-1].text == user_message:
        turns = turns[:-1]

    keep = rounds * 2
    turns = turns[-keep:]

    return [{"role": item.role, "content": item.text} for item in turns]



def run_chat(
    user_message: str,
    llm_config: dict,
    history: List[dict],
    image_data_url: Optional[str] = None,
) -> ChatResult:
    client = _load_env_client()

    try:
        cfg = LLMConfig.model_validate(llm_config)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid llm config: {exc}")

    parsed_history = [ChatTurn.model_validate(item) for item in history]

    rag_context = None
    rag_score = 0.0
    if cfg.rag:
        rag_context, rag_score = _retrieve_top_qa(client, user_message)
        if rag_score < 0.72:
            rag_context = None

    system_prompt = build_system_prompt(base_prompt=cfg.system_prompt, rag_context=rag_context)

    messages = [{"role": "system", "content": system_prompt}]
    if cfg.memory:
        messages.extend(_build_memory_messages(parsed_history, user_message, cfg.memory_rounds))

    if image_data_url:
        _validate_image_data_url(image_data_url)
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=cfg.model,
        temperature=cfg.temperature,
        messages=messages,
    )

    answer = response.choices[0].message.content or ""
    if rag_context and "Reference: QA #" not in answer:
        answer = f"{answer}\n\n(Reference: QA #{rag_context['id']})"

    return ChatResult(
        reply=answer,
        used_rag=rag_context is not None,
        reference_qa_id=(rag_context["id"] if rag_context else None),
    )


def generate_chat_title(seed_message: str, llm_config: dict) -> str:
    client = _load_env_client()
    try:
        cfg = LLMConfig.model_validate(llm_config)
    except ValidationError:
        cfg = LLMConfig()

    prompt = (
        "你是對話標題生成器。請根據使用者訊息生成一個繁體中文聊天室標題，"
        "長度 6 到 18 字，不要標點，不要引號，不要換行。"
    )
    response = client.chat.completions.create(
        model=cfg.model,
        temperature=0.4,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": seed_message},
        ],
    )
    title = (response.choices[0].message.content or "").strip()
    title = title.replace("\n", " ").replace("\"", "").replace("'", "")
    return title[:24] if title else "新聊天室"
