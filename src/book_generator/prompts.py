import json

from .models import BookConfig, BookPlan, ChapterPlan, plan_schema

SYSTEM = """You are an author of original educational books for AI Generation Library.
Use the requested language and audience level. Treat the supplied outline and references as source data.
Write original explanations; do not copy lengthy copyrighted passages. Never invent verified sources,
test results, benchmarks, or claims of human review. Distinguish assumptions from established facts.
Do not execute code or access URLs. Avoid raw HTML, scripts, YAML frontmatter and filesystem instructions.
"""


def plan_prompt(config: BookConfig) -> str:
    return f"""Plan an educational book with exactly {config.chapter_count} chapters in continuous parts.
Keep the requested title: {config.title}
Language: {config.language}; audience: {config.audience}
Return ONLY a JSON object matching this schema, with no commentary:
{json.dumps(plan_schema(), ensure_ascii=False)}
Topic and author-supplied data:
{json.dumps({"subject": config.subject, "outline": config.outline, "references": config.references}, ensure_ascii=False)}
Each chapter must have a useful description and distinct learning objectives. Build from prerequisites
to applied examples. Do not claim the reference links have been fetched or verified.
"""


def chapter_prompt(config: BookConfig, plan: BookPlan, number: int, chapter: ChapterPlan) -> str:
    outline = [
        {"number": index, "part": part, "title": item.title, "summary": item.summary}
        for index, (part, item) in enumerate(plan.chapters(), 1)
    ]
    return f"""Write chapter {number} of "{config.title}" as a substantial Markdown manuscript.
Language: {config.language}; audience: {config.audience}
Chapter specification: {chapter.model_dump_json()}
Whole-book outline: {json.dumps(outline, ensure_ascii=False)}
Author inputs: {json.dumps({"subject": config.subject, "outline": config.outline, "references": config.references}, ensure_ascii=False)}
Begin with '# {number:02d}장. {chapter.title}'. Explain the motivation, concepts and practical choices in
connected prose. Include concrete examples, a guided exercise, questions and a closing recap appropriate
to the topic. Technical examples must explain prerequisites, expected behavior, and failure cases.
Make uncertainty explicit. Provide reference links only when supported by the supplied sources;
otherwise list topics for further verification without inventing citations. Do not claim examples ran.
Return Markdown only, without wrapping the whole answer in a code fence. Do not use frontmatter.
Keep the chapter within the available output limit and finish all paragraphs and code fences.
"""


def demo_plan(config: BookConfig) -> BookPlan:
    chapters = [
        {
            "title": f"학습 단계 {number}",
            "summary": f"{config.subject}의 {number}번째 학습 단계",
            "objectives": ["핵심 질문 정리하기", "예제를 검토하고 검증 계획 만들기"],
        }
        for number in range(1, config.chapter_count + 1)
    ]
    return BookPlan.model_validate(
        {
            "description": f"{config.title} · API를 호출하지 않는 데모 원고",
            "parts": [{"title": "데모 학습 과정", "chapters": chapters}],
        }
    )


def demo_chapter(config: BookConfig, number: int, chapter: ChapterPlan) -> str:
    return f"""# {number:02d}장. {chapter.title}

> **데모 원고입니다.** AI API를 호출하지 않고 파일 구조와 생성 흐름을 확인하기 위해 만든 예시입니다.

## 이번 장의 목표

주제는 **{config.title}**입니다. 실제 집필에서는 대상 독자의 사전 지식과 학습 목표에 맞추어
개념, 예제, 실습을 연결합니다. 이 데모는 지식 설명을 대신하지 않습니다.

## 학습을 설계하는 방법

먼저 독자가 답하고 싶은 질문을 한 문장으로 적습니다. 질문에 필요한 용어를 정리하고,
작은 예제를 통해 설명이 맞는지 확인합니다. 관찰한 결과와 예상 결과가 다르면 원인을 기록합니다.

## 직접 해 보기

1. 이번 주제의 핵심 질문을 세 개 적어 보세요.
2. 확인할 수 있는 공식 자료를 찾아 출처와 날짜를 기록하세요.
3. 예제와 설명을 검토하고 미확인 내용을 표시하세요.

## 확인할 질문

- 어떤 사전 지식이 필요한가요?
- 설명을 뒷받침할 예제와 근거가 있나요?
- 독자가 확인해야 할 제한은 무엇인가요?

## 정리

생성된 원고는 검토가 필요한 초안입니다. 실제 API 키와 모델을 입력하면 같은 흐름으로
책 기획과 장별 원고를 작성합니다. 실습 실행과 사실 확인은 저자가 별도로 수행합니다.
"""
