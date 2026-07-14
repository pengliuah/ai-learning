import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Document } from '../api/types'
import { PlanDetail } from '../pages/PlanDetail'
import { buildDoc, buildModule, renderAtRoute } from './helpers'

vi.mock('../api/client', () => ({
  api: {
    getPlan: vi.fn(),
    deletePlan: vi.fn(),
  } as unknown as typeof import('../api/client')['api'],
}))

import { api } from '../api/client'

describe('PlanDetail progress calc', () => {
  beforeEach(() => {
    vi.mocked(api.getPlan).mockReset()
  })

  it('shows 33% when 1 of 3 modules is completed', async () => {
    const doc = buildDoc([
      buildModule({ id: 'm1', status: 'completed' }),
      buildModule({ id: 'm2', status: 'not_started' }),
      buildModule({ id: 'm3', status: 'not_started' }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { container, findByText } = renderAtRoute(<PlanDetail />, '/plans/:planId', '/plans/plan-1')
    await findByText('Plan Title')
    expect(container.textContent).toContain('33%')
  })

  it('shows 100% when all modules are completed', async () => {
    const doc = buildDoc([
      buildModule({ id: 'm1', status: 'completed' }),
      buildModule({ id: 'm2', status: 'completed' }),
    ])
    vi.mocked(api.getPlan).mockResolvedValue(doc)

    const { container, findByText } = renderAtRoute(<PlanDetail />, '/plans/:planId', '/plans/plan-1')
    await findByText('Plan Title')
    expect(container.textContent).toContain('100%')
  })
})
