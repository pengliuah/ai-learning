export type Level = "beginner" | "intermediate" | "advanced";
export type Difficulty = "easy" | "medium" | "hard";
export type ModuleStatus = "not_started" | "studying" | "completed";
export type QuestionType = "mcq" | "mcq_multi" | "short";

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
  /** mcq_multi (多选) 的全部正确选项 */
  answers: string[];
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

export interface ImaSettings {
  imaClientId: string;
  imaApiKey: string;
  imaSkillPrompt: string;
}

export interface ImaSettingsUpdate {
  imaClientId?: string | null;
  imaApiKey?: string | null;
  imaSkillPrompt?: string | null;
}

export interface GenSettings {
  plan: string;
  content: string;
  quiz: string;
}

export interface GenSettingsUpdate {
  plan?: string | null;
  content?: string | null;
  quiz?: string | null;
}

export interface ModelSettings {
  apiKey: string;
  model: string;
  baseUrl: string;
  maxTokens: number;
}

export interface ModelSettingsUpdate {
  apiKey?: string | null;
  model?: string | null;
  baseUrl?: string | null;
  maxTokens?: number | null;
}

export interface UsageStat {
  requests: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface UsageSummary {
  today: UsageStat;
  month: UsageStat;
  allTime: UsageStat;
}

export type SaveToImaContentType = "plan" | "content" | "quiz" | "result";

export interface SaveToImaRequest {
  moduleId?: string | null;
  contentType?: SaveToImaContentType | null;
  skillPromptOverride?: string | null;
}

export interface SaveToImaResponse {
  ok: boolean;
  noteId: string | null;
  title: string;
  detail: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

// ---------------------------------------------------------------------------
// Auth（账号系统）
// ---------------------------------------------------------------------------

export type UserRole = "admin" | "user";

export interface User {
  id: string;
  username: string;
  email: string | null;
  role: UserRole;
  createdAt: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  user: User;
}

export interface AdminUserCreateInput {
  username: string;
  password: string;
  role?: UserRole;
  email?: string | null;
}

export interface Annotation {
  id: string;
  planId: string;
  moduleKey: string;
  quote: string;
  prefix: string;
  suffix: string;
  note: string;
  createdAt: string;
  updatedAt: string;
}
