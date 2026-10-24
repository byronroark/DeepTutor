import React from 'react'
import {render,screen,waitFor} from '@testing-library/react'
import {beforeEach,expect,it,vi} from 'vitest'
import {FamilyLearningLink} from '@/components/sidebar/FamilyLearningLink'

const mock=vi.hoisted(()=>({admin:true,authenticated:true,fetch:vi.fn()}))
vi.mock('@/hooks/useAuthStatus',()=>({useAuthStatus:()=>({isAdmin:mock.admin,authenticated:mock.authenticated})}))
vi.mock('@/shared/api/client',()=>({apiFetch:mock.fetch}))
vi.mock('next/navigation',()=>({usePathname:()=>'/family-learning'}))
vi.mock('next/link',()=>({default:({prefetch,children,...props}:React.ComponentProps<'a'>&{prefetch?:boolean})=><a {...props}>{children}</a>}))
beforeEach(()=>{mock.admin=true;mock.authenticated=true;mock.fetch.mockReset();mock.fetch.mockResolvedValue({ok:true})})

it('gives parents a direct sidebar link when Family Learning is enabled',async()=>{
  render(<FamilyLearningLink/>)
  expect((await screen.findByRole('link',{name:'Family Learning'})).getAttribute('href')).toBe('/family-learning')
  expect(screen.getByRole('link',{name:'Family Learning'})).toHaveAttribute('aria-current','page')
})
it('keeps an accessible icon link when the sidebar is collapsed',async()=>{
  render(<FamilyLearningLink collapsed/>)
  expect((await screen.findByRole('link',{name:'Family Learning'})).getAttribute('title')).toBe('Family Learning')
})
it('does not expose the parent shortcut to learners',()=>{
  mock.admin=false
  render(<FamilyLearningLink/>)
  expect(screen.queryByRole('link',{name:'Family Learning'})).toBeNull()
  expect(mock.fetch).not.toHaveBeenCalled()
})
it('hides the shortcut when the local feature is disabled or unavailable',async()=>{
  mock.fetch.mockResolvedValue({ok:false})
  render(<FamilyLearningLink/>)
  await waitFor(()=>expect(mock.fetch).toHaveBeenCalledOnce())
  expect(screen.queryByRole('link',{name:'Family Learning'})).toBeNull()
})
