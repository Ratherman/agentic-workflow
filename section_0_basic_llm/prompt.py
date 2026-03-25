from typing import Optional


RAG_GUIDELINE = """
當有提供檢索內容時，請先判斷是否與使用者問題直接相關。
如果不相關，請忽略檢索內容，不要硬套答案。
""".strip()



def build_system_prompt(base_prompt: str, rag_context: Optional[dict]) -> str:
    sections = [base_prompt.strip(), RAG_GUIDELINE]

    if rag_context:
        sections.append(
            "\n".join(
                [
                    "【RAG Retrieved QA】",
                    f"id: {rag_context['id']}",
                    f"question: {rag_context['question']}",
                    f"answer: {rag_context['answer']}",
                ]
            )
        )
    else:
        sections.append("【RAG Retrieved QA】\nNone")

    sections.append(
        "回覆要求：\n"
        "1) 先直接回答使用者問題。\n"
        "2) 若使用了 RAG 內容，請在最後標示 (Reference: QA #id)。\n"
        "3) 若未使用 RAG，請不要虛構 reference。\n"
        "4) 若使用者附上圖片，請先描述你看到的關鍵內容，再回答問題。\n"
        "5) 在事實一致前提下，盡量避免與前一輪回答完全相同措辭，可用不同句型自然表達。"
    )

    return "\n\n".join(sections)
