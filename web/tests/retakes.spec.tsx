import React from 'react'
import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {beforeEach,expect,it,vi} from 'vitest'
import {AttemptHistory,RetakeControls} from '@/app/family-learning/Retakes'

const mock=vi.hoisted(()=>({fetch:vi.fn()}))
vi.mock('@/shared/api/client',()=>({apiFetch:mock.fetch}))
beforeEach(()=>vi.clearAllMocks())

it('requires parent confirmation and sends the selected lesson and attempt version',async()=>{
  const saved=vi.fn().mockResolvedValue(undefined)
  mock.fetch.mockResolvedValue({ok:true,json:async()=>({saved:true})})
  render(<RetakeControls course="course" assignments={[{learner:'child',active:1,epoch:4}]} lessons={[{id:'loop',title:'Loops'}]} name={()=>'Learner'} onSaved={saved}/>)
  expect(screen.getByRole('button',{name:'Retake course'}).hasAttribute('disabled')).toBe(true)
  fireEvent.change(screen.getByLabelText('Learner for retake'),{target:{value:'child'}})
  fireEvent.change(screen.getByLabelText('What to retake'),{target:{value:'loop'}})
  fireEvent.click(screen.getByLabelText('Preserve previous results and start a fresh attempt.'))
  fireEvent.click(screen.getByRole('button',{name:'Retake lesson'}))
  await waitFor(()=>expect(saved).toHaveBeenCalledOnce())
  const [path,options]=mock.fetch.mock.calls[0]
  expect(path).toBe('/api/family-learning/courses/course/retake')
  expect(JSON.parse(options.body)).toMatchObject({learner:'child',lesson:'loop',expected_epoch:4})
  expect(await screen.findByText('Retake started. Previous results are saved. The learner should refresh their course.')).toBeTruthy()
})

it('shows preserved results as tries rather than inventing a numeric grade',()=>{
  render(<AttemptHistory entries={[{id:'old',learner:'child',scope:'loop',archived_at:'2026-10-22T12:00:00Z',results:[{lesson:'loop',state:'passed',attempts:3,feedback:'Good loop!'}]}]} lessons={[{id:'loop',title:'Loops'}]}/>)
  fireEvent.click(screen.getByText(/Loops ·/))
  expect(screen.getByText('passed · 3 tries')).toBeTruthy()
  expect(screen.getByText('Good loop!')).toBeTruthy()
})

it('reuses the same reset request after a transport failure',async()=>{
  mock.fetch.mockRejectedValueOnce(new Error('Connection lost')).mockResolvedValueOnce({ok:true,json:async()=>({saved:true})})
  render(<RetakeControls course="course" assignments={[{learner:'child',active:1,epoch:0}]} lessons={[]} name={()=>'Learner'} onSaved={vi.fn().mockResolvedValue(undefined)}/>)
  fireEvent.change(screen.getByLabelText('Learner for retake'),{target:{value:'child'}})
  fireEvent.click(screen.getByLabelText('Preserve previous results and start a fresh attempt.'))
  fireEvent.click(screen.getByRole('button',{name:'Retake course'}))
  await screen.findByText('Connection lost')
  await waitFor(()=>expect(screen.getByRole('button',{name:'Retake course'}).hasAttribute('disabled')).toBe(false))
  fireEvent.click(screen.getByRole('button',{name:'Retake course'}))
  await waitFor(()=>expect(mock.fetch).toHaveBeenCalledTimes(2))
  expect(mock.fetch.mock.calls[0][1].body).toBe(mock.fetch.mock.calls[1][1].body)
})
