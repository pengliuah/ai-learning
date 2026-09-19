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
  grade: string;
}

export interface GenSettingsUpdate {
  plan?: string | null;
  content?: string | null;
  quiz?: string | null;
  grade?: string | null;
}

export interface ModelSettings {
  apiKey: string;
  model: string;
  baseUrl: string;
  maxTokens: number;
  embeddingApiKey: string;
  embeddingModel: string;
  embeddingBaseUrl: string;
  visionApiKey: string;
  visionModel: string;
  visionBaseUrl: string;
}

export interface ModelSettingsUpdate {
  apiKey?: string | null;
  model?: string | null;
  baseUrl?: string | null;
  maxTokens?: number | null;
  embeddingApiKey?: string | null;
  embeddingModel?: string | null;
  embeddingBaseUrl?: string | null;
  visionApiKey?: string | null;
  visionModel?: string | null;
  visionBaseUrl?: string | null;
}

/** 上传的学习资料附件（转写状态: pending/running/done/failed） */
export interface Attachment {
  id: string;
  filename: string;
  mime: string;
  sizeBytes: number;
  transcriptStatus: "pending" | "running" | "done" | "failed";
  transcript: string;
  createdAt?: string | null;
  /** 上传命中同文件去重: 返回的是已有记录, 未写盘建新行 */
  reused?: boolean;
}

export interface UsageStat {
  requests: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface UsageSummary {
  today: UsageByKind;
  month: UsageByKind;
  allTime: UsageByKind;
}

/** 按模型类型拆分的用量：llm=大模型，embedding=向量模型，vision=多模态（附件转写） */
export interface UsageByKind {
  llm: UsageStat;
  embedding: UsageStat;
  vision: UsageStat;
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

// 书签列表项（跨计划/模块聚合，GET /api/annotations）
export interface BookmarkItem {
  id: string;
  planId: string;
  planTitle: string;
  moduleId: string;
  moduleTitle: string | null;
  quote: string;
  note: string;
  createdAt: string;
}

// 长期记忆（Mem0 事实，GET /api/memories）
export interface MemoryItem {
  id: string;
  memory: string;
  createdAt: string | null;
  updatedAt: string | null;
  category?: string | null;
  importance?: number | null;
  superseded?: boolean;
}

// 学生画像（长期记忆摘要层，GET/PUT /api/memories/profile）
export interface MemoryProfile {
  profile: string;
  updatedAt: string | null;
  editedByUser: boolean;
}

export interface MemorySettings {
  enabled: boolean;
}

export interface MemorySettingsUpdate {
  enabled?: boolean;
}
