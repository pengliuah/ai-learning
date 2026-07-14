import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import type { Document, GradingResult, Module, Plan, Quiz } from '../api/types'

export function renderAtRoute(element: ReactElement, path: string, route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

export function buildModule(overrides: Partial<Module> = {}): Module {
  return {
    id: overrides.id ?? 'm1',
    title: overrides.title ?? 'Module One',
    summary: overrides.summary ?? 'a module summary',
    objectives: overrides.objectives ?? ['objective one'],
    minutes: overrides.minutes ?? 30,
    difficulty: overrides.difficulty ?? 'medium',
    status: overrides.status ?? 'not_started',
    content: overrides.content ?? null,
    quiz: overrides.quiz ?? null,
    result: overrides.result ?? null,
    answers: overrides.answers ?? null,
  }
}

export function buildDoc(modules: Module[], opts: { id?: string; title?: string } = {}): Document {
  const plan: Plan = {
    title: opts.title ?? 'Plan Title',
    goal: 'the goal',
    summary: 'the summary',
    level: 'intermediate',
    totalMinutes: 90,
    modules,
  }
  return {
    id: opts.id ?? 'plan-1',
    createdAt: '2026-07-01T00:00:00.000Z',
    updatedAt: '2026-07-01T00:00:00.000Z',
    source: { input: 'a topic', mode: 'topic' },
    plan,
  }
}

export function sampleQuiz(): Quiz {
  return {
    questions: [
      {
        id: 'q1',
        type: 'mcq',
        prompt: '1+1=?',
        options: ['1', '2', '3'],
        answer: '2',
        modelAnswer: null,
        keyPoints: [],
        explanation: 'addition',
      },
      {
        id: 'q2',
        type: 'short',
        prompt: 'describe a decorator',
        options: [],
        answer: null,
        modelAnswer: 'a callable wrapping a function',
        keyPoints: ['callable', 'no source change'],
        explanation: 'concept',
      },
    ],
  }
}

export function sampleResult(): GradingResult {
  return {
    results: [
      { questionId: 'q1', score: 1, maxScore: 1, correct: true, feedback: 'correct', studentAnswer: '2' },
      { questionId: 'q2', score: 0.5, maxScore: 1, correct: false, feedback: 'partial', studentAnswer: 'my answer' },
    ],
    totalScore: 1.5,
    maxScore: 2,
    assessment: {
      strengths: ['strength A'],
      weaknesses: ['weakness A'],
      recommendations: ['rec A'],
      level: 'intermediate',
    },
  }
}
