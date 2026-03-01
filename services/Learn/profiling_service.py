from datetime import datetime, timezone
import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.Learn.quiz_model import Quiz
from models.Learn.user_learn_model import ProfilingResults, SubtopicProgressUser
from services.Learn.answer_utils import is_selected_correct

DIFFICULTY_LEVELS = ("basic", "core", "mastery")


def _stable_pick(items, key_fn, limit: int, seed: str):
    ranked = sorted(
        items,
        key=lambda item: hashlib.sha256(
            f"{seed}:{key_fn(item)}".encode("utf-8")
        ).hexdigest(),
    )
    return ranked[:limit]


def _normalize_answers(answers: dict) -> dict[int, str]:
    if not isinstance(answers, dict) or not answers:
        raise HTTPException(status_code=400, detail="Answers must be a non-empty object")

    normalized: dict[int, str] = {}
    for raw_qid, selected in answers.items():
        try:
            qid = int(raw_qid)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid question id '{raw_qid}'")
        if qid in normalized:
            raise HTTPException(status_code=400, detail=f"Duplicate question id '{qid}'")
        normalized[qid] = selected
    return normalized


class ProfilingService:
    @staticmethod
    async def start(db: AsyncSession, user_id: str, subtopic_id: int):
        """Return a deterministic set of profiling questions (3 per difficulty)."""
        questions: dict[str, list[Quiz]] = {}
        for diff in DIFFICULTY_LEVELS:
            candidates = (
                (
                    await db.execute(
                        select(Quiz).where(
                            Quiz.subtopic_id == subtopic_id,
                            Quiz.difficulty == diff,
                            Quiz.is_published.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(candidates) < 3:
                raise HTTPException(
                    status_code=404,
                    detail=f"Not enough profiling questions for difficulty '{diff}'",
                )

            seed = f"profiling:{user_id}:{subtopic_id}:{diff}"
            questions[diff] = _stable_pick(candidates, lambda q: q.question_id, 3, seed)
        return questions

    @staticmethod
    async def submit(db: AsyncSession, user_id: str, subtopic_id: int, answers: dict):
        progress = (
            await db.execute(
                select(SubtopicProgressUser).where(
                    SubtopicProgressUser.user_id == user_id,
                    SubtopicProgressUser.subtopic_id == subtopic_id,
                )
            )
        ).scalar_one_or_none()

        if not progress or progress.stage != "profiling":
            raise HTTPException(409, "Profiling not allowed")

        normalized_answers = _normalize_answers(answers)
        expected_by_difficulty = await ProfilingService.start(db, user_id, subtopic_id)
        expected_questions = [
            question
            for difficulty in DIFFICULTY_LEVELS
            for question in expected_by_difficulty[difficulty]
        ]
        expected_ids = {question.question_id for question in expected_questions}

        if set(normalized_answers.keys()) != expected_ids:
            raise HTTPException(
                status_code=400,
                detail="Submitted questions do not match the issued profiling quiz",
            )

        scores = {"basic": 0, "core": 0, "mastery": 0}
        for question in expected_questions:
            selected = normalized_answers.get(question.question_id)
            if is_selected_correct(selected, question.content_json) and question.difficulty in scores:
                scores[question.difficulty] += 1

        starting_difficulty = max(scores, key=scores.get)

        db.add(
            ProfilingResults(
                user_id=user_id,
                topic_id=progress.topic_id,
                subtopic_id=subtopic_id,
                basic_score=scores["basic"],
                core_score=scores["core"],
                mastery_score=scores["mastery"],
                assigned_difficulty=starting_difficulty,
            )
        )

        progress.stage = "content"
        progress.starting_difficulty = starting_difficulty
        progress.current_difficulty = starting_difficulty
        progress.updated_at = datetime.now(timezone.utc)

        await db.commit()
        return {"assigned_difficulty": starting_difficulty, "scores": scores}
