import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { ProgressBar } from '../components/ProgressBar'

describe('ProgressBar', () => {
  it('sets the bar width to the rounded percentage', () => {
    const { container } = render(<ProgressBar value={0.5} />)
    const bar = container.querySelector('[style]') as HTMLElement
    expect(bar.style.width).toBe('50%')
  })

  it('reaches 100% at full value', () => {
    const { container } = render(<ProgressBar value={1} />)
    const bar = container.querySelector('[style]') as HTMLElement
    expect(bar.style.width).toBe('100%')
  })

  it('rounds a fractional percentage', () => {
    const { container } = render(<ProgressBar value={1 / 3} />)
    const bar = container.querySelector('[style]') as HTMLElement
    expect(bar.style.width).toBe('33%')
  })
})
