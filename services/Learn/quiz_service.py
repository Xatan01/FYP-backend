import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.Learn.quiz_model import Quiz
from models.Learn.user_learn_model import (
    LLMGeneratedQuestions,
    QuizAttemptQuestions,
    QuizAttempts,
    SubtopicProgressUser,
)
from services.Learn.answer_utils import is_selected_correct
from services.Learn.progress_service import ProgressService
from services.gamification_service import GamificationService

VALID_DIFFICULTIES = {"basic", "core", "mastery"}
MAX_ATTEMPTS = 3
STANDARD_QUESTION_LIMIT = 4
LLM_QUESTION_LIMIT = 2
MIN_STANDARD_CORRECT = 3
MIN_TOTAL_CORRECT = 4


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


def _required_standard_correct(standard_question_count: int) -> int:
    return min(MIN_STANDARD_CORRECT, max(0, int(standard_question_count or 0)))


def _required_total_correct(total_question_count: int) -> int:
    total = max(0, int(total_question_count or 0))
    if total <= STANDARD_QUESTION_LIMIT:
        return _required_standard_correct(total)
    return min(MIN_TOTAL_CORRECT, total)


class QuizService:
    @staticmethod
    async def _get_attempt_number(
        db: AsyncSession,
        user_id: str,
        subtopic_id: int,
        difficulty: str,
    ) -> int:
        return (
            (
                await db.execute(
                    select(func.count())
                    .select_from(QuizAttempts)
                    .where(
                        QuizAttempts.user_id == user_id,
                        QuizAttempts.subtopic_id == subtopic_id,
                        QuizAttempts.difficulty == difficulty,
                    )
                )
            ).scalar_one()
            + 1
        )

    @staticmethod
    async def _build_expected_quiz(
        db: AsyncSession,
        user_id: str,
        subtopic_id: int,
        difficulty: str,
        attempt_number: int,
    ):
        standard_candidates = (
            (
                await db.execute(
                    select(Quiz).where(
                        Quiz.subtopic_id == subtopic_id,
                        Quiz.difficulty == difficulty,
                        Quiz.is_published.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(standard_candidates) < 4:
            raise HTTPException(status_code=404, detail="Not enough published standard questions")

        standard_seed = f"quiz:{user_id}:{subtopic_id}:{difficulty}:{attempt_number}:standard"
        standard_questions = _stable_pick(
            standard_candidates,
            lambda q: q.question_id,
            STANDARD_QUESTION_LIMIT,
            standard_seed,
        )

        llm_candidates = (
            (
                await db.execute(
                    select(LLMGeneratedQuestions).where(
                        LLMGeneratedQuestions.subtopic_id == subtopic_id,
                        LLMGeneratedQuestions.difficulty == difficulty,
                    )
                )
            )
            .scalars()
            .all()
        )
        llm_seed = f"quiz:{user_id}:{subtopic_id}:{difficulty}:{attempt_number}:llm"
        llm_questions = _stable_pick(
            llm_candidates,
            lambda q: q.llm_question_id,
            LLM_QUESTION_LIMIT,
            llm_seed,
        )

        # Use negative IDs for LLM questions to avoid clashes with standard IDs.
        expected = {}
        for question in standard_questions:
            expected[question.question_id] = ("standard", question)
        for question in llm_questions:
            expected[-int(question.llm_question_id)] = ("llm", question)

        return standard_questions, llm_questions, expected

    @staticmethod
    async def start(db: AsyncSession, user_id: str, subtopic_id: int, difficulty: str):
        """Return 4 deterministic standard questions + up to 2 deterministic LLM questions."""
        if difficulty not in VALID_DIFFICULTIES:
            raise HTTPException(status_code=400, detail="Invalid difficulty")

        progress = (
            await db.execute(
                select(SubtopicProgressUser).where(
                    SubtopicProgressUser.user_id == user_id,
                    SubtopicProgressUser.subtopic_id == subtopic_id,
                )
            )
        ).scalar_one_or_none()
        if not progress:
            raise HTTPException(status_code=409, detail="Progress not initialized")
        if progress.stage not in {"content", "quiz"}:
            raise HTTPException(409, "Quiz not allowed at this stage")

        await ProgressService.ensure_subtopic_is_unlocked(
            db,
            user_id,
            progress.topic_id,
            subtopic_id,
        )

        attempt_number = await QuizService._get_attempt_number(
            db,
            user_id,
            subtopic_id,
            difficulty,
        )
        if attempt_number > MAX_ATTEMPTS:
            raise HTTPException(409, "Maximum attempts reached")

        standard_questions, llm_questions, _ = await QuizService._build_expected_quiz(
            db,
            user_id,
            subtopic_id,
            difficulty,
            attempt_number,
        )

        if progress.stage == "content":
            progress.stage = "quiz"
            await db.commit()

        return standard_questions + llm_questions

    @staticmethod
    async def submit_attempt(
        db: AsyncSession,
        user_id: str,
        subtopic_id: int,
        difficulty: str,
        answers: dict,
    ):
        if difficulty not in VALID_DIFFICULTIES:
            raise HTTPException(status_code=400, detail="Invalid difficulty")

        progress = (
            await db.execute(
                select(SubtopicProgressUser).where(
                    SubtopicProgressUser.user_id == user_id,
                    SubtopicProgressUser.subtopic_id == subtopic_id,
                )
            )
        ).scalar_one_or_none()
        if not progress or progress.stage != "quiz":
            raise HTTPException(409, "Quiz not allowed at this stage")

        await ProgressService.ensure_subtopic_is_unlocked(
            db,
            user_id,
            progress.topic_id,
            subtopic_id,
        )

        attempt_number = await QuizService._get_attempt_number(
            db,
            user_id,
            subtopic_id,
            difficulty,
        )
        if attempt_number > MAX_ATTEMPTS:
            raise HTTPException(409, "Maximum attempts reached")

        _, _, expected_questions = await QuizService._build_expected_quiz(
            db,
            user_id,
            subtopic_id,
            difficulty,
            attempt_number,
        )
        expected_ids = set(expected_questions.keys())

        normalized_answers = _normalize_answers(answers)
        if set(normalized_answers.keys()) != expected_ids:
            raise HTTPException(
                status_code=400,
                detail="Submitted questions do not match the issued quiz",
            )

        total_correct = 0
        standard_correct = 0
        attempt = QuizAttempts(
            user_id=user_id,
            topic_id=progress.topic_id,
            subtopic_id=subtopic_id,
            difficulty=difficulty,
            attempt_number=attempt_number,
            total_questions=len(expected_ids),
            correct_count=0,
            passed=False,
            points_awarded=0,
            created_at=_now_utc(),
        )
        db.add(attempt)
        await db.flush()

        for question_id in sorted(expected_ids):
            source, question = expected_questions[question_id]
            selected = normalized_answers[question_id]
            is_correct = is_selected_correct(selected, question.content_json)
            total_correct += int(is_correct)
            if source == "standard":
                standard_correct += int(is_correct)

            db.add(
                QuizAttemptQuestions(
                    quiz_attempt_id=attempt.quiz_attempt_id,
                    question_id=question_id,
                    question_source=source,
                    is_correct=is_correct,
                )
            )

        standard_question_count = sum(
            1 for source, _question in expected_questions.values() if source == "standard"
        )
        total_question_count = len(expected_ids)
        required_standard = _required_standard_correct(standard_question_count)
        required_total = _required_total_correct(total_question_count)

        attempt.correct_count = total_correct
        attempt.passed = (
            standard_correct >= required_standard
            and total_correct >= required_total
        )
        attempt.points_awarded = GamificationService.calculate_quiz_xp(
            total_correct,
            difficulty,
            attempt.passed,
            attempt_number=attempt_number,
        )

        if attempt.passed or attempt_number >= MAX_ATTEMPTS:
            progress.stage = "explanation"

        await GamificationService.record_quiz_attempt_xp(db, attempt)
        await db.commit()

        retries_remaining = max(0, MAX_ATTEMPTS - attempt_number)
        can_retry = (not attempt.passed) and retries_remaining > 0
        next_retry_multiplier = (
            GamificationService.retry_xp_multiplier(attempt_number + 1)
            if can_retry
            else None
        )

        return {
            "attempt_number": attempt_number,
            "passed": attempt.passed,
            "total_correct": total_correct,
            "standard_correct": standard_correct,
            "standard_questions": standard_question_count,
            "required_standard_correct": required_standard,
            "points_awarded": attempt.points_awarded,
            "required_correct": required_total,
            "total_questions": total_question_count,
            "can_retry": can_retry,
            "retries_remaining": retries_remaining,
            "retry_xp_multiplier": GamificationService.retry_xp_multiplier(attempt_number),
            "next_retry_xp_multiplier": next_retry_multiplier,
        }

    @staticmethod
    async def get_explanation(db: AsyncSession, user_id: str, subtopic_id: int, difficulty: str):
        """Return all answered questions + correctness for explanation stage."""
        progress = (
            await db.execute(
                select(SubtopicProgressUser).where(
                    SubtopicProgressUser.user_id == user_id,
                    SubtopicProgressUser.subtopic_id == subtopic_id,
                )
            )
        ).scalar_one_or_none()
        if not progress:
            raise HTTPException(status_code=409, detail="Progress not initialized")
        if progress.stage not in {"explanation", "summary", "completed"}:
            raise HTTPException(status_code=409, detail="Explanation not available at this stage")

        attempts = (
            (
                await db.execute(
                    select(QuizAttempts).where(
                        QuizAttempts.user_id == user_id,
                        QuizAttempts.subtopic_id == subtopic_id,
                        QuizAttempts.difficulty == difficulty,
                    )
                )
            )
            .scalars()
            .all()
        )
        attempt_ids = [attempt.quiz_attempt_id for attempt in attempts]
        if not attempt_ids:
            return []

        attempt_questions = (
            (
                await db.execute(
                    select(QuizAttemptQuestions).where(
                        QuizAttemptQuestions.quiz_attempt_id.in_(attempt_ids)
                    )
                )
            )
            .scalars()
            .all()
        )

        explanations = []
        for question in attempt_questions:
            explanations.append(
                {
                    "question_id": question.question_id,
                    "source": question.question_source,
                    "is_correct": question.is_correct,
                }
            )
        return explanations
