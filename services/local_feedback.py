from __future__ import annotations

import math
import re
from collections import Counter
from itertools import combinations
from statistics import mean
from typing import Any


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

STOPWORDS = {
    "a",
    "about",
    "after",
    "again",
    "all",
    "also",
    "am",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "before",
    "but",
    "by",
    "can",
    "could",
    "do",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "should",
    "so",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "to",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
}

DIRECT_MARKERS = {
    "i would",
    "i will",
    "my first step",
    "the main issue",
    "yes",
    "no",
    "my view",
    "i believe",
}
STRUCTURE_MARKERS = {
    "first",
    "second",
    "then",
    "finally",
    "initially",
    "next",
    "overall",
    "in summary",
    "my priority",
}
EMPATHY_MARKERS = {
    "listen",
    "feel",
    "feeling",
    "concern",
    "support",
    "acknowledge",
    "understand",
    "respect",
    "comfortable",
    "perspective",
    "privately",
}
ETHICS_MARKERS = {
    "consent",
    "confidential",
    "confidentiality",
    "autonomy",
    "benefit",
    "harm",
    "fair",
    "fairness",
    "duty",
    "safety",
    "privacy",
    "capacity",
}
PROFESSIONAL_MARKERS = {
    "boundary",
    "boundaries",
    "confidential",
    "document",
    "escalate",
    "guidance",
    "policy",
    "scope",
    "supervisor",
    "instructor",
    "safety",
}
CRITICAL_MARKERS = {
    "however",
    "although",
    "balance",
    "trade-off",
    "tradeoff",
    "alternative",
    "risk",
    "unless",
    "depends",
    "on the other hand",
    "whereas",
    "if",
}
FILLERS = {"um", "uh", "like", "basically", "actually", "literally"}


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text or "")]


def _content_tokens(text: str) -> set[str]:
    return {token for token in _tokens(text) if token not in STOPWORDS and len(token) > 2}


def _contains_any(text: str, markers: set[str]) -> int:
    lowered = (text or "").lower()
    return sum(
        1
        for marker in markers
        if re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", lowered)
    )


def _bounded(value: float, lower: float = 0.0, upper: float = 10.0) -> float:
    return max(lower, min(upper, value))


def _score_from_hits(base: float, hits: int, increment: float = 1.25) -> float:
    return _bounded(base + min(hits, 4) * increment)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _repetition(responses: list[dict[str, Any]]) -> dict[str, Any]:
    token_sets = [_content_tokens(response.get("transcript", "")) for response in responses]
    pairs = []
    similarities = []
    for left, right in combinations(range(len(token_sets)), 2):
        similarity = _jaccard(token_sets[left], token_sets[right])
        similarities.append(similarity)
        if similarity >= 0.55:
            pairs.append(
                {
                    "questions": [left + 1, right + 1],
                    "similarity": round(similarity, 2),
                }
            )

    term_counts: Counter[str] = Counter()
    for token_set in token_sets:
        term_counts.update(token_set)
    repeated_terms = [term for term, count in term_counts.most_common() if count >= 3][:6]
    maximum = max(similarities, default=0.0)
    return {
        "detected": maximum >= 0.65 or len(pairs) >= 2,
        "max_similarity": round(maximum, 2),
        "pairs": pairs,
        "repeated_terms": repeated_terms,
        "message": (
            "四个回答之间有明显内容复用；下一轮请让每一问只完成自己的任务。"
            if maximum >= 0.65 or len(pairs) >= 2
            else "四个回答的分工基本清楚，没有发现严重的跨题重复。"
        ),
    }


def _question_scores(text: str, duration_seconds: float) -> dict[str, float]:
    tokens = _tokens(text)
    word_count = len(tokens)
    if word_count == 0:
        return {
            "directness": 0.0,
            "structure": 0.0,
            "empathy": 0.0,
            "ethical_reasoning": 0.0,
            "professionalism": 0.0,
            "critical_thinking": 0.0,
            "communication": 0.0,
            "delivery": 0.0,
        }
    first_words = " ".join(tokens[:18])

    direct_hits = _contains_any(first_words, DIRECT_MARKERS)
    directness = 2.5 if word_count == 0 else _score_from_hits(4.5, direct_hits, 2.0)
    if word_count < 12:
        directness -= 1.5

    structure_hits = _contains_any(text, STRUCTURE_MARKERS)
    sentence_count = max(1, len([part for part in SENTENCE_RE.split(text.strip()) if part]))
    structure = _score_from_hits(4.0, structure_hits, 1.1)
    if sentence_count >= 3:
        structure += 0.5

    empathy = _score_from_hits(3.5, _contains_any(text, EMPATHY_MARKERS), 1.15)
    ethics = _score_from_hits(3.5, _contains_any(text, ETHICS_MARKERS), 1.05)
    professionalism = _score_from_hits(3.8, _contains_any(text, PROFESSIONAL_MARKERS), 1.0)
    critical = _score_from_hits(3.5, _contains_any(text, CRITICAL_MARKERS), 1.0)

    filler_count = sum(1 for token in tokens if token in FILLERS)
    communication = 6.0
    if 55 <= word_count <= 130:
        communication += 1.0
    elif word_count < 20 or word_count > 170:
        communication -= 1.5
    communication -= min(2.0, filler_count * 0.3)

    if duration_seconds > 0:
        wpm = word_count / duration_seconds * 60
        if 90 <= wpm <= 150:
            delivery = 7.5
        elif 70 <= wpm < 90 or 150 < wpm <= 175:
            delivery = 6.0
        else:
            delivery = 4.5
    else:
        delivery = 5.0

    return {
        "directness": round(_bounded(directness), 1),
        "structure": round(_bounded(structure), 1),
        "empathy": round(_bounded(empathy), 1),
        "ethical_reasoning": round(_bounded(ethics), 1),
        "professionalism": round(_bounded(professionalism), 1),
        "critical_thinking": round(_bounded(critical), 1),
        "communication": round(_bounded(communication), 1),
        "delivery": round(_bounded(delivery), 1),
    }


def _evidence(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "（没有可评估的 transcript）"
    first_sentence = SENTENCE_RE.split(cleaned, maxsplit=1)[0]
    return first_sentence[:180]


def _question_feedback(scores: dict[str, float], word_count: int, wpm: float | None) -> tuple[str, str, str]:
    strongest = max(scores, key=scores.get)
    weakest = min(scores, key=scores.get)
    strong_labels = {
        "directness": "开头比较直接，能较快让考官知道你的立场。",
        "structure": "回答有可跟随的顺序，不是散点堆叠。",
        "empathy": "有先理解人的感受和处境，再进入解决方案。",
        "ethical_reasoning": "能识别价值、义务或潜在伤害，而不只是给操作步骤。",
        "professionalism": "能说明边界、责任和必要时升级的条件。",
        "critical_thinking": "能看到权衡、风险或条件变化。",
        "communication": "表达长度和句子组织比较适合一分钟回答。",
        "delivery": "按 transcript 与时长估算，语速处于可理解范围。",
    }
    improve_labels = {
        "directness": "第一句话先直接回答问题，再解释理由；不要用背景铺垫占掉开头。",
        "structure": "只保留一个明确答案和最多两个展开点，并用简短路标连接。",
        "empathy": "补一句对当事人感受或视角的承认，再进入任务处理。",
        "ethical_reasoning": "明确说出核心价值冲突，以及为什么你的选择能减少伤害。",
        "professionalism": "补清楚你的权限边界、保密要求，以及什么时候才升级。",
        "critical_thinking": "加入一个真实的反方风险或条件句，说明你的方案何时需要改变。",
        "communication": "删去重复措辞，让每句话只承担一个功能。",
        "delivery": "把答案控制在约 90–120 个英文词，并用停顿替代填充词。",
    }
    next_actions = {
        "directness": "重录时强制以 “I would…” 或一句明确判断开头。",
        "structure": "先在 15 秒内只记：结论 / 人 / 事 / 边界。",
        "empathy": "第二句话必须出现 listen、acknowledge 或 perspective 中的一个动作。",
        "ethical_reasoning": "加入一句 “The tension is between … and …”。",
        "professionalism": "加入一句明确的升级阈值，而不是立即找上级。",
        "critical_thinking": "加入一个 however 或 if 条件，随后说明应对。",
        "communication": "删掉一个重复观点，把整段压缩 15%。",
        "delivery": "用 50–58 秒完成一次 90–120 词重录。",
    }

    improve = improve_labels[weakest]
    if word_count > 140:
        improve = "内容偏多；一分钟内只展开两个 substantive ideas，并删掉提前回答后续问题的部分。"
    elif word_count < 25:
        improve = "内容偏短；在明确立场后补一个理由和一个具体行动，让回答形成完整闭环。"
    elif wpm and wpm > 175:
        improve = "语速估算偏快；减少内容而不是加速说完，目标是清楚地讲 90–120 个词。"

    return strong_labels[strongest], improve, next_actions[weakest]


def _answer_structure(question_text: str) -> list[str]:
    """Return a short, question-specific 1–2–1 speaking plan for fallback coaching."""

    question = str(question_text or "").lower()
    if "stakeholder" in question or "evidence" in question or "consult" in question:
        return [
            "先回应任务：说明你会先听取相关方并核对证据，再形成建议。",
            "相关方：选 1–2 组最关键的人，并说明他们能提供什么视角。",
            "证据：选 1–2 类最有用的数据，并说明它们如何影响判断。",
            "最后收束：用这些信息作出透明、可解释的决定。",
        ]
    if "compare" in question or "comparison" in question or "options" in question:
        return [
            "先给比较标准：用一句话说明你会依据什么判断。",
            "展开点 1：比较谁最需要帮助，以及哪个方案能最快降低风险。",
            "展开点 2：比较覆盖范围、可行性或长期公平性；最多选一个补充标准。",
            "最后收束：说清核心取舍；除非题目要求，不必提前作最终选择。",
        ]
    if "choose" in question or "justify" in question or "recommend" in question:
        return [
            "先明确选择：直接说 “I would choose…”；不要先复述所有选项。",
            "展开核心理由：最多两个，并解释为什么它们比其他标准更重要。",
            "承认一个主要局限，并给出简短的缓解办法。",
            "最后收束：重申当前最优先保护的人、价值或结果。",
        ]
    if "longer term" in question or "long term" in question or "prepare" in question:
        return [
            "先定目标：说明长期准备要减少什么风险、提升什么能力。",
            "展开点 1：讲清一个具体系统机制，以及它怎样发挥作用。",
            "展开点 2：再补一个不同层面的机制；不要罗列完整政策清单。",
            "最后收束：说明由谁协调，以及如何复盘成效。",
        ]
    if "impartial" in question or "neutral" in question or "take sides" in question:
        return [
            "先表态：你的目标是公平处理，而不是判断谁的人品更好。",
            "分别倾听并核对事实：给双方同样的表达机会，不先下结论。",
            "使用一致标准处理问题，例如团队责任、影响和已有约定。",
            "最后收束：不站队；只有持续影响他人或任务时才升级。",
        ]
    if "outcome" in question or "aim for" in question or "success" in question:
        return [
            "先说理想结果：用一句话明确你希望最终实现什么。",
            "兼顾人：让相关者被尊重、能够继续合作或获得支持。",
            "兼顾事：说明任务、安全或公平方面怎样才算改善。",
            "最后收束：追求可行结果，而不是强迫关系或情绪立刻恢复。",
        ]
    if "should" in question or "would you intervene" in question:
        return [
            "先给立场：直接回答 yes / no / it depends，并说明适用条件。",
            "展开最重要的理由：解释介入或不介入会保护什么。",
            "说明行动边界：你会做到哪一步、不会越过什么权限。",
            "最后收束：给出只有风险持续时才采用的升级条件。",
        ]
    if "reflect" in question or "learn" in question or "experience" in question:
        return [
            "先直接回答：点明一个真实经历、变化或认识。",
            "展开点 1：给一个具体细节，说明当时你怎么想、怎么做。",
            "展开点 2：解释这件事怎样改变了你后来的行为。",
            "最后收束：把学习落到未来的具体做法，而不是抽象品质。",
        ]
    if "approach" in question or "respond" in question or "what would you do" in question:
        return [
            "先表态：一句话说明你的首要目标和第一步。",
            "先处理人或事实：倾听、澄清，并确认最重要的风险。",
            "再处理事情：提出一个可执行方案，并说明为什么合适。",
            "最后收束：说明边界，以及什么情况下才需要升级。",
        ]
    return [
        "先直接回答：第一句话明确回应题目，不先重复背景。",
        "展开点 1：选择最重要的理由或行动，并解释它为什么重要。",
        "展开点 2：只在确实有帮助时再补一个不同角度。",
        "最后收束：用 priority、boundary 或 outcome 结束。",
    ]


def evaluate_locally(station: dict[str, Any], responses: list[dict[str, Any]]) -> dict[str, Any]:
    questions = station.get("questions", [])
    model_answers = station.get("model_answers", [])
    question_results = []
    all_scores: list[dict[str, float]] = []

    for index, question in enumerate(questions):
        response = responses[index] if index < len(responses) else {}
        text = str(response.get("transcript", "") or "").strip()
        try:
            duration = float(response.get("duration_seconds", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
        tokens = _tokens(text)
        word_count = len(tokens)
        wpm = round(word_count / duration * 60, 1) if duration > 0 else None
        scores = _question_scores(text, duration)
        all_scores.append(scores)
        worked, improve, next_action = _question_feedback(scores, word_count, wpm)
        model_answer = model_answers[index] if index < len(model_answers) else ""
        question_text = question.get("text", "") if isinstance(question, dict) else str(question)

        question_results.append(
            {
                "question_number": index + 1,
                "question": question_text,
                "scores": scores,
                "worked": worked,
                "improve": improve,
                "evidence": _evidence(text),
                "next_action": next_action,
                "answer_structure": _answer_structure(question_text),
                "model_answer": model_answer,
                "word_count": word_count,
                "wpm": wpm,
            }
        )

    dimensions = {
        key: round(mean(score[key] for score in all_scores), 1)
        for key in (
            "directness",
            "structure",
            "empathy",
            "ethical_reasoning",
            "professionalism",
            "critical_thinking",
            "communication",
            "delivery",
        )
    } if all_scores else {}

    repetition = _repetition(responses)
    overall = round(mean(dimensions.values()), 1) if dimensions else 0.0
    if repetition["detected"]:
        overall = round(_bounded(overall - 0.5), 1)

    weakest_dimension = min(dimensions, key=dimensions.get) if dimensions else "structure"
    next_focus_map = {
        "directness": "每一问第一句直接回答，不先复述题目。",
        "structure": "用“明确答案 + 最多两个展开点 + 收束”完成一分钟。",
        "empathy": "人际题先让对方被听见，再进入解决方案。",
        "ethical_reasoning": "把价值冲突说出来，而不只列步骤。",
        "professionalism": "说明边界和升级阈值。",
        "critical_thinking": "加入一个真实权衡或条件变化。",
        "communication": "删掉重复和长句，让每句话只做一件事。",
        "delivery": "控制在 90–120 个英文词，并保留自然停顿。",
    }
    next_focus = (
        "四问分工：本轮只练习不重复前一问已经说过的理由和步骤。"
        if repetition["detected"]
        else next_focus_map[weakest_dimension]
    )

    if overall >= 7.5:
        summary = "这次回答已经较清楚、有边界；下一步重点是让四问之间的分工更精确。"
    elif overall >= 5.5:
        summary = "核心思路可用，但部分回答仍像通用模板；需要更直接、更贴合当前问题。"
    else:
        summary = "目前最值得优先练的是结构和取舍：先给结论，再只展开最重要的内容。"

    return {
        "provider": "local",
        "model": "deterministic-coach-v1",
        "rubric_version": "melbourne-coaching-v1",
        "summary": summary,
        "overall_score": overall,
        "dimensions": dimensions,
        "next_focus": next_focus,
        "repetition": repetition,
        "questions": question_results,
        "disclaimer": "练习辅导分，不是 University of Melbourne 官方评分或录取预测。",
    }
