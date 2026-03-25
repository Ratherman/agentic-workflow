import hashlib
import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

DATA_DIR = Path(__file__).resolve().parent / "sample_data"
QA_PATH = DATA_DIR / "company_qa.json"
VECTOR_DB_PATH = DATA_DIR / "qa_vectors.json"



def deterministic_embedding(text: str, dim: int = 64) -> list:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = list(digest) * ((dim // len(digest)) + 1)
    return [((seed[i] / 255.0) * 2.0) - 1.0 for i in range(dim)]



def build_vector_db() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)

    api_key = os.getenv("OPENAI_API_KEY")
    embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    client = OpenAI(api_key=api_key) if api_key else None

    qa_data = json.loads(QA_PATH.read_text(encoding="utf-8-sig"))
    vector_data = []
    use_fallback = False

    for qa in qa_data:
        text = f"Q: {qa['question']}\nA: {qa['answer']}"
        try:
            if client is None:
                raise RuntimeError("missing OPENAI_API_KEY")
            resp = client.embeddings.create(model=embedding_model, input=[text])
            embedding = resp.data[0].embedding
        except Exception:
            use_fallback = True
            embedding = deterministic_embedding(text)

        vector_data.append(
            {
                "id": qa["id"],
                "question": qa["question"],
                "answer": qa["answer"],
                "embedding": embedding,
            }
        )

    VECTOR_DB_PATH.write_text(json.dumps(vector_data, ensure_ascii=False), encoding="utf-8")
    if use_fallback:
        print("Vector DB generated with fallback embeddings (OpenAI embedding unavailable).")
    else:
        print("Vector DB generated with OpenAI embeddings.")
    print(f"Path: {VECTOR_DB_PATH}")


if __name__ == "__main__":
    build_vector_db()
