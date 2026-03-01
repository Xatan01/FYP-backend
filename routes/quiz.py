from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.Learn.quiz_model import Quiz
from routes.auth import require_user
from schemas.Learn.quiz_schema import QuestionOut
from services.database import get_db

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/{subtopic_id:int}/{difficulty}", response_model=list[QuestionOut])
async def get_quiz(subtopic_id: int, difficulty: str, db: Session = Depends(get_db)):
    print(
        f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /quiz/{subtopic_id}/{difficulty} called",
        flush=True,
    )

    questions = (
        db.query(Quiz)
        .filter(
            Quiz.subtopic_id == subtopic_id,
            Quiz.difficulty == difficulty,
            Quiz.is_published.is_(True),
        )
        .order_by(Quiz.question_id.asc())
        .all()
    )

    if not questions:
        print(
            f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /quiz/{subtopic_id}/{difficulty} quiz not found",
            flush=True,
        )
        raise HTTPException(status_code=404, detail="Quiz not found")

    return [
        QuestionOut(
            question_id=question.question_id,
            subtopic_id=question.subtopic_id,
            question_type=question.question_type,
            title=(
                question.content_json.get("title")
                if isinstance(question.content_json, dict)
                else f"Question {question.question_id}"
            )
            or f"Question {question.question_id}",
            question_json=question.content_json if isinstance(question.content_json, dict) else {},
            is_published=question.is_published,
        )
        for question in questions
    ]
    

@router.get("/profiling/{subtopic_id}", response_model=list[QuestionOut])
async def get_profiling_quiz(subtopic_id: int, db: Session = Depends(get_db)):
    print(
        f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /quiz/profiling/{subtopic_id} called",
        flush=True,
    )

    difficulty_levels = ("basic", "core", "mastery")
    profiling_questions = []

    for difficulty in difficulty_levels:
        questions = (
            db.query(Quiz)
            .filter(
                Quiz.subtopic_id == subtopic_id,
                Quiz.difficulty == difficulty,
                Quiz.is_published.is_(True),
            )
            .order_by(func.random())
            .limit(3)
            .all()
        )

        if len(questions) < 3:
            print(
                f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /quiz/profiling/{subtopic_id} insufficient questions for difficulty={difficulty}",
                flush=True,
            )
            raise HTTPException(
                status_code=404,
                detail=f"Not enough published profiling questions for difficulty '{difficulty}'",
            )

        profiling_questions.extend(questions)

    return [
        QuestionOut(
            question_id=question.question_id,
            subtopic_id=question.subtopic_id,
            question_type=question.question_type,
            title=(
                question.content_json.get("title")
                if isinstance(question.content_json, dict)
                else f"Question {question.question_id}"
            )
            or f"Question {question.question_id}",
            question_json=question.content_json if isinstance(question.content_json, dict) else {},
            is_published=question.is_published,
        )
        for question in profiling_questions
    ]
