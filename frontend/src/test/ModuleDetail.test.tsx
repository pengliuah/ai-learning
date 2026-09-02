import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import { ModuleDetail } from '../pages/ModuleDetail'
import { buildDoc, buildModule, sampleQuiz, sampleResult, renderAtRoute } from './helpers'

vi.mock('../api/client', () => ({
  api: {
    getPlan: vi.fn(),
    saveAnswers: vi.fn(),
    gradeQuiz: vi.fn(),
    generateQuiz: vi.fn(),
    streamContent: vi.fn(),
    saveToIma: vi.fn(),
  } as unknown as typeof import('../api/client')['api'],
}))

import { api } from '../api/client'

describe('ModuleDetail', () => {
  beforeEach(() => {
    vi.mocked(api.getPlan).mockReset()
    vi.mocked(api.saveAnswers).mockReset()
    vi.mocked(api.gradeQuiz).mockReset()
  })
  afterEach(() => {
    vi.clearAllTimers()
  })

  it('records an MCQ answer and submits it for grading', async () => {
    const doc = buildDoc([buildModule({ id: 'm1', quiz: sampleQuiz() })])
    vi.mocked(api.getPlan).mockResolvedValue(doc)
    vi.mocked(api.saveAnswers).mockResolvedValue(doc)
    const graded = buildDoc([
      buildModule({ id: 'm1', quiz: sampleQuiz(), result: sampleResult(), status: 'completed' }),
    ])
    vi.mocked(api.gradeQuiz).mockResolvedValue(graded)

    const { findByText, findByLabelText } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    const quizTab = await findByText('测验')
    fireEvent.click(quizTab)

    const opt2 = await findByLabelText('2')
    fireEvent.click(opt2)
    expect(opt2).toBeChecked()

    const submit = await findByText('提交批改')
    fireEvent.click(submit)

    await waitFor(() => expect(vi.mocked(api.gradeQuiz)).toHaveBeenCalledWith('plan-1', 'm1'))
    await findByText('批改结果')
  })

  it('renders grading results: score, assessment, per-question review', async () => {
    const doc = buildDoc([
      buildModule({ id: 'm1', quiz: sampleQuiz(), result: sampleResult(), status: 'completed' }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { container, findByText } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    await findByText('批改结果')
    expect(container.textContent).toContain('1.5')
    expect(container.textContent).toContain('75')
    expect(container.textContent).toContain('优势')
    expect(container.textContent).toContain('不足')
    expect(container.textContent).toContain('建议')
    expect(container.textContent).toContain('正确答案')
    expect(container.textContent).toContain('你的答案')
    expect(container.textContent).toContain('反馈')
    expect(container.textContent).toContain('重做')
    expect(container.textContent).toContain('重新学习')
  })

  it('"重做" returns to the quiz answering tab', async () => {
    const doc = buildDoc([
      buildModule({ id: 'm1', quiz: sampleQuiz(), result: sampleResult(), status: 'completed' }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { findByText } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    await findByText('批改结果')
    fireEvent.click(await findByText('重做'))

    await findByText('提交批改')
  })

  it('"重新学习" returns to the content tab', async () => {
    const doc = buildDoc([
      buildModule({ id: 'm1', quiz: sampleQuiz(), result: sampleResult(), status: 'completed' }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { findByText } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    await findByText('批改结果')
    fireEvent.click(await findByText('重新学习'))

    await findByText('生成学习内容')
  })

  it('autosaves the latest answer value, not a stale snapshot', async () => {
    const doc = buildDoc([buildModule({ id: 'm1', quiz: sampleQuiz() })])
    vi.mocked(api.getPlan).mockResolvedValue(doc)
    vi.mocked(api.saveAnswers).mockResolvedValue(doc)

    const { findByText, findByRole } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    fireEvent.click(await findByText('测验'))
    const textarea = (await findByRole('textbox')) as HTMLTextAreaElement

    fireEvent.change(textarea, { target: { value: 'a' } })
    fireEvent.change(textarea, { target: { value: 'ab' } })
    fireEvent.change(textarea, { target: { value: 'abc' } })

    await waitFor(() => expect(vi.mocked(api.saveAnswers)).toHaveBeenCalled(), { timeout: 3000 })

    const saved = vi.mocked(api.saveAnswers).mock.calls[0][2]
    expect(saved).toMatchObject({ q2: 'abc' })
  })

  it('renders LaTeX math in content (incl. CJK subscripts) via KaTeX', async () => {
    const doc = buildDoc([
      buildModule({
        id: 'm1',
        content: {
          markdown: '浮力公式：$F_{浮} = 10\\text{N}$',
          keyTakeaways: [],
        },
      }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { container } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    await waitFor(() => expect(container.querySelector('.katex')).not.toBeNull(), { timeout: 3000 })
    // CJK subscript is tagged for font fallback (no missing-glyph boxes)
    expect(container.querySelector('.cjk_fallback')).not.toBeNull()
    // the $...$ delimiters are consumed by KaTeX, not shown as raw text
    expect(container.textContent).not.toContain('$')
  })
  it('renders math and bold in key takeaways, not raw markdown', async () => {
    const doc = buildDoc([
      buildModule({
        id: 'm1',
        content: {
          markdown: '正文内容，无公式。',
          keyTakeaways: ['**方向与符号**：符号记为 $F_{浮}$，单位是牛顿（$\\text{N}$）。'],
        },
      }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { container } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    await waitFor(() => expect(container.querySelector('.katex')).not.toBeNull(), { timeout: 3000 })
    expect(container.querySelector('.cjk_fallback')).not.toBeNull()
    expect(container.textContent).not.toContain('**')
    expect(container.textContent).not.toContain('$')
  })

  it('renders LaTeX math in quiz prompts and options via KaTeX', async () => {
    const doc = buildDoc([
      buildModule({
        id: 'm1',
        quiz: {
          questions: [
            {
              id: 'q1',
              type: 'mcq',
              prompt: '化简 $\\frac{1}{2} + \\frac{1}{2}$ 的结果是？',
              options: ['$\\frac{1}{2}$', '$1$', '$\\frac{1}{4}$'],
              answer: '$1$',
              answers: [],
modelAnswer: null,
              keyPoints: [],
              explanation: '同分母相加',
            },
          ],
        },
      }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { container, findByText } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    fireEvent.click(await findByText('测验'))

    await waitFor(() => expect(container.querySelector('.katex')).not.toBeNull(), { timeout: 3000 })
    // $...$ delimiters are consumed by KaTeX, not shown as raw text
    expect(container.textContent).not.toContain('$')
  })

  it('renders LaTeX math in grading results (answers, key points, feedback)', async () => {
    const doc = buildDoc([
      buildModule({
        id: 'm1',
        status: 'completed',
        quiz: {
          questions: [
            {
              id: 'q1',
              type: 'short',
              prompt: '求 $x^2 = 4$ 的解',
              options: [],
              answer: null,
              answers: [],
              modelAnswer: '解为 $x = \\pm 2$',
              keyPoints: ['$x^2$ 的根成对出现', '记号 $\\pm$'],
              explanation: '',
            },
          ],
        },
        result: {
          results: [
            { questionId: 'q1', score: 1, maxScore: 1, correct: true, feedback: '正确，$\\pm 2$ 是对的', studentAnswer: '$x = 2$' },
          ],
          totalScore: 1,
          maxScore: 1,
          assessment: { strengths: ['掌握 $\\pm$ 符号'], weaknesses: [], recommendations: [], level: 'intermediate' },
        },
      }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { container, findByText } = renderAtRoute(
      <ModuleDetail />,
      '/plans/:planId/modules/:moduleId',
      '/plans/plan-1/modules/m1',
    )

    await findByText('批改结果')
    await waitFor(() => expect(container.querySelector('.katex')).not.toBeNull(), { timeout: 3000 })
    expect(container.textContent).not.toContain('$')
  })

  it("shows a regenerate button when content already exists", async () => {
    const doc = buildDoc([
      buildModule({
        id: "m1",
        content: { markdown: "# existing content", keyTakeaways: [] },
      }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)
    const { findAllByText } = renderAtRoute(
      <ModuleDetail />,
      "/plans/:planId/modules/:moduleId",
      "/plans/plan-1/modules/m1",
    )
    await findAllByText("重新生成")
  })

  it("shows a regenerate button when quiz already exists", async () => {
    const doc = buildDoc([buildModule({ id: "m1", quiz: sampleQuiz() })])
    vi.mocked(api.getPlan).mockResolvedValue(doc)
    const { findByText } = renderAtRoute(
      <ModuleDetail />,
      "/plans/:planId/modules/:moduleId",
      "/plans/plan-1/modules/m1",
    )
    fireEvent.click(await findByText("测验"))
    await findByText("重新生成")
  })

  it("regenerating quiz calls the API and shows new questions", async () => {
    const doc = buildDoc([buildModule({ id: "m1", quiz: sampleQuiz() })])
    vi.mocked(api.getPlan).mockResolvedValue(doc)
    const regenerated = buildDoc([
      buildModule({
        id: "m1",
        quiz: {
          questions: [
            { id: "q1", type: "mcq", prompt: "new question", options: ["a", "b"], answer: "a", answers: [], modelAnswer: null, keyPoints: [], explanation: "" },
          ],
        },
      }),
    ])
    vi.mocked(api.generateQuiz).mockResolvedValue(regenerated)
    const { findByText } = renderAtRoute(
      <ModuleDetail />,
      "/plans/:planId/modules/:moduleId",
      "/plans/plan-1/modules/m1",
    )
    fireEvent.click(await findByText("测验"))
    fireEvent.click(await findByText("重新生成"))
    await waitFor(() => expect(vi.mocked(api.generateQuiz)).toHaveBeenCalledWith("plan-1", "m1"))
    await findByText("new question")
  })


})
