from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.Learn.learn_schema import SubtopicSummaryOut
from schemas.Learn.quiz_schema import ExplanationItemOut, QuestionOut, QuizSubmitResultOut
from services.database import get_db
from services.Learn.profiling_service import ProfilingService
from services.Learn.progress_service import ProgressService
from services.Learn.quiz_service import QuizService

router = APIRouter(dependencies=[Depends(require_user)])


def _to_question_out(question) -> QuestionOut:
    content_json = question.content_json if isinstance(question.content_json, dict) else {}
    if hasattr(question, "question_id"):
        question_id = question.question_id
        question_type = question.question_type
        is_published = question.is_published
    else:
        # Use negative IDs for LLM questions to avoid collisions with standard question IDs.
        question_id = -int(question.llm_question_id)
        question_type = content_json.get("question_type", "llm")
        is_published = True

    title = content_json.get("title") or f"Question {abs(int(question_id))}"
    return QuestionOut(
        question_id=int(question_id),
        subtopic_id=question.subtopic_id,
        question_type=question_type,
        title=title,
        question_json=content_json,
        is_published=is_published,
    )


@router.get("/profiling/{subtopic_id}/start", response_model=list[QuestionOut])
async def start_profiling(
    subtopic_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """
    Return profiling questions (3 per difficulty).
    """
    questions_by_difficulty = await ProfilingService.start(db, user["sub"], subtopic_id)
    ordered_questions = []
    for difficulty in ("basic", "core", "mastery"):
        ordered_questions.extend(questions_by_difficulty.get(difficulty, []))
    return [_to_question_out(question) for question in ordered_questions]


@router.post("/profiling/{subtopic_id}/submit")
async def submit_profiling(
    subtopic_id: int,
    answers: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """
    Submit profiling quiz answers and assign starting difficulty.
    """
    return await ProfilingService.submit(db, user["sub"], subtopic_id, answers)


@router.get("/{subtopic_id}/{difficulty}/start", response_model=list[QuestionOut])
async def start_quiz(
    subtopic_id: int,
    difficulty: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """
    Return 5 standard questions + up to 2 LLM questions.
    """
    questions = await QuizService.start(db, user["sub"], subtopic_id, difficulty)
    return [_to_question_out(question) for question in questions]


@router.post("/{subtopic_id}/{difficulty}/submit", response_model=QuizSubmitResultOut)
async def submit_quiz(
    subtopic_id: int,
    difficulty: str,
    answers: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """
    Submit regular quiz answers, calculate points, update progress stage.
    """
    return await QuizService.submit_attempt(db, user["sub"], subtopic_id, difficulty, answers)


@router.get("/{subtopic_id}/{difficulty}/explanation", response_model=list[ExplanationItemOut])
async def get_explanation(
    subtopic_id: int,
    difficulty: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """
    Get explanation stage details (is_correct per question).
    """
    return await QuizService.get_explanation(db, user["sub"], subtopic_id, difficulty)


@router.get("/{subtopic_id}/summary", response_model=SubtopicSummaryOut)
async def get_summary(
    subtopic_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    """
    Get the latest published summary for a subtopic.
    """
    summary = await ProgressService.get_subtopic_summary(
        db,
        subtopic_id,
        user["sub"],
    )
    return SubtopicSummaryOut(
        summary_id=summary.summary_id,
        topic_id=summary.topic_id,
        subtopic_id=summary.subtopic_id,
        summary_content=summary.summary_content,
        is_published=summary.is_published,
    )
