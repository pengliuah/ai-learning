export type Level = "beginner" | "intermediate" | "advanced";
export type Difficulty = "easy" | "medium" | "hard";
export type ModuleStatus = "not_started" | "studying" | "completed";
export type QuestionType = "mcq" | "short";

export interface Content {
  markdown: string;
  keyTakeaways: string[];
}

export interface Question {
  id: string;
  type: QuestionType;
  prompt: string;
  options: string[];
  answer: string | null;
  modelAnswer: string | null;
  keyPoints: string[];
  explanation: string;
}

export interface Quiz {
  questions: Question[];
}

export interface Assessment {
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  level: Level;
}

export interface QuestionResult {
  questionId: string;
  score: number;
  maxScore: number;
  correct: boolean;
  feedback: string;
  studentAnswer: string;
}

export interface GradingResult {
  results: QuestionResult[];
  totalScore: number;
  maxScore: number;
  assessment: Assessment;
}

export interface Module {
  id: string;
  title: string;
  summary: string;
  objectives: string[];
  minutes: number;
  difficulty: Difficulty;
  status: ModuleStatus;
  content: Content | null;
  quiz: Quiz | null;
  result: GradingResult | null;
  answers: Record<string, string> | null;
}

export interface Plan {
  title: string;
  goal: string;
  summary: string;
  level: Level;
  totalMinutes: number;
  modules: Module[];
}

export interface PlanSource {
  input: string;
  mode: "topic" | "materials";
}

export interface Document {
  id: string;
  createdAt: string;
  updatedAt: string;
  source: PlanSource;
  plan: Plan;
}

export interface PlanListItem {
  id: string;
  title: string;
  createdAt: string;
  progress: number;
}

export interface AnswersState {
  answers: Record<string, string>;
  answered: number;
  total: number;
}
