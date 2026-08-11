from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Level(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class Difficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class ModuleStatus(str, Enum):
    not_started = "not_started"
    studying = "studying"
    completed = "completed"


class QuestionType(str, Enum):
    mcq = "mcq"
    short = "short"


class Content(BaseModel):
    markdown: str
    keyTakeaways: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    type: QuestionType
    prompt: str
    options: list[str] = Field(default_factory=list)
    answer: str | None = None
    modelAnswer: str | None = None
    keyPoints: list[str] = Field(default_factory=list)
    explanation: str = ""


class Quiz(BaseModel):
    questions: list[Question] = Field(default_factory=list)


class Assessment(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    level: Level = Level.intermediate


class QuestionResult(BaseModel):
    questionId: str
    score: float
    maxScore: float
    correct: bool
    feedback: str = ""
    # 学生原始作答：批改后保留，便于结果页回看
    studentAnswer: str = ""


class GradingResult(BaseModel):
    results: list[QuestionResult] = Field(default_factory=list)
    totalScore: float = 0.0
    maxScore: float = 0.0
    assessment: Assessment = Field(default_factory=Assessment)


class Module(BaseModel):
    id: str
    title: str
    summary: str
    objectives: list[str] = Field(default_factory=list)
    minutes: int = 0
    difficulty: Difficulty = Difficulty.medium
    status: ModuleStatus = ModuleStatus.not_started
    content: Content | None = None
    quiz: Quiz | None = None
    result: GradingResult | None = None
    # 测验作答草稿：questionId -> 学生作答文本，随答随存，提交批改时读取
    answers: dict[str, str] | None = None


class Plan(BaseModel):
    title: str
    goal: str
    summary: str = ""
    level: Level = Level.intermediate
    totalMinutes: int = 0
    modules: list[Module] = Field(default_factory=list)


class PlanSource(BaseModel):
    input: str
    mode: Literal["topic", "materials"] = "topic"


class Document(BaseModel):
    id: str
    createdAt: datetime
    updatedAt: datetime
    source: PlanSource
    plan: Plan


class PlanCreateRequest(BaseModel):
    input: str
    mode: Literal["topic", "materials"] = "topic"


class PlanListItem(BaseModel):
    id: str
    title: str
    createdAt: datetime
    progress: float = 0.0


class ModuleStatusPatch(BaseModel):
    status: ModuleStatus


# 保存（合并）测验作答草稿的请求体
class SaveAnswersRequest(BaseModel):
    answers: dict[str, str]


# 作答草稿与进度（GET answers 返回）
class AnswersState(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    answered: int = 0
    total: int = 0


class CoachRequest(BaseModel):
    goal: str


# ---------------------------------------------------------------------------
# App settings (IMA credentials + skill prompt, regeneration strategy)
# ---------------------------------------------------------------------------

class ImaSettings(BaseModel):
    imaClientId: str = ""
    imaApiKey: str = ""
    imaSkillPrompt: str = ""


class ImaSettingsUpdate(BaseModel):
    """PUT /api/settings/ima request body. All fields optional so partial
    updates are possible (e.g. save only the skill prompt)."""
    imaClientId: str | None = None
    imaApiKey: str | None = None
    imaSkillPrompt: str | None = None


class GenSettings(BaseModel):
    plan: str = ""
    content: str = ""
    quiz: str = ""


class GenSettingsUpdate(BaseModel):
    plan: str | None = None
    content: str | None = None
    quiz: str | None = None


class SaveToImaRequest(BaseModel):
    """Save-to-IMA request body.

    - ``moduleId``: if set, save that module's content; otherwise save the
      whole plan overview.
    - ``contentType``: what to save -- "plan" (overview), "content" (module
      learning content), "quiz" (quiz questions), "result" (grading results
      with answer analysis). Defaults to "plan" when no moduleId, "content"
      when moduleId is given.
    - ``skillPromptOverride``: if set, use this prompt instead of the stored
      IMA skill prompt to drive formatting.
    """
    moduleId: str | None = None
    contentType: str | None = None
    skillPromptOverride: str | None = None


class SaveToImaResponse(BaseModel):
    ok: bool
    noteId: str | None = None
    title: str = ""
    detail: str = ""