import React from 'react'
import { fireEvent,render,screen,waitFor } from '@testing-library/react'
import { beforeEach,expect,it,vi } from 'vitest'
import CourseImport from '@/app/family-learning/CourseImport'

const mock=vi.hoisted(()=>({fetch:vi.fn()}))
vi.mock('@/shared/api/client',()=>({apiFetch:mock.fetch}))
const course={title:'Pet simulator',subject:'Python',objectives:['Use variables'],lessons:[{id:'pets',title:'Count pets',kind:'python',explanation:'Variables store values.',question:'Print 3.',starter_code:'pets = 3',expected_output:'3\n',requirements:['assignment'],hints:['Use print(pets).'],success:'Well done!'}]}
const document=JSON.stringify({format:'family-learning-course',version:1,course})
beforeEach(()=>vi.clearAllMocks())

it('requires private review before publishing and never assigns automatically',async()=>{
  const published=vi.fn().mockResolvedValue(undefined)
  mock.fetch.mockImplementation(async(path:string)=>({ok:true,json:async()=>path.endsWith('/preview')?{course}:{id:'new-course'}}))
  render(<CourseImport onPublished={published}/>)
  fireEvent.click(screen.getByText('Import an AI-prepared course'))
  fireEvent.change(screen.getByLabelText('Course JSON'),{target:{value:document}})
  fireEvent.click(screen.getByRole('button',{name:'Validate and review'}))
  expect(await screen.findByText('Pet simulator')).toBeTruthy()
  expect(mock.fetch).toHaveBeenCalledTimes(1)
  expect(published).not.toHaveBeenCalled()
  const publish=screen.getByRole('button',{name:'Publish reviewed course'})
  expect(publish.hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByLabelText('I reviewed the explanations, exercises, hints, and answer expectations.'))
  fireEvent.click(publish)
  await waitFor(()=>expect(published).toHaveBeenCalledWith('new-course'))
  expect(mock.fetch.mock.calls.map(([path])=>path)).toEqual(['/api/family-learning/imports/preview','/api/family-learning/imports/publish'])
})

it('invalidates the review if the JSON changes and shows validation errors',async()=>{
  mock.fetch.mockResolvedValueOnce({ok:true,json:async()=>({course})}).mockResolvedValueOnce({ok:false,json:async()=>({detail:'Lesson IDs must be unique slugs'})})
  render(<CourseImport onPublished={vi.fn()}/>)
  fireEvent.click(screen.getByText('Import an AI-prepared course'))
  fireEvent.change(screen.getByLabelText('Course JSON'),{target:{value:document}})
  fireEvent.click(screen.getByRole('button',{name:'Validate and review'}))
  await screen.findByText('Pet simulator')
  fireEvent.change(screen.getByLabelText('Course JSON'),{target:{value:'{}'}})
  expect(screen.queryByRole('button',{name:'Publish reviewed course'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'Validate and review'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Lesson IDs must be unique slugs')
})

it('rejects oversized files before reading them',async()=>{
  const read=vi.fn()
  render(<CourseImport onPublished={vi.fn()}/>)
  fireEvent.click(screen.getByText('Import an AI-prepared course'))
  fireEvent.change(screen.getByLabelText('Course JSON file'),{target:{files:[{size:1_000_001,text:read}]}})
  expect(await screen.findByRole('alert')).toHaveTextContent('at most 1 MB')
  expect(read).not.toHaveBeenCalled();expect(mock.fetch).not.toHaveBeenCalled()
})

it('loads a selected JSON file without publishing or validating automatically',async()=>{
  render(<CourseImport onPublished={vi.fn()}/>)
  fireEvent.click(screen.getByText('Import an AI-prepared course'))
  fireEvent.change(screen.getByLabelText('Course JSON file'),{target:{files:[{size:document.length,text:async()=>document}]}})
  await waitFor(()=>expect((screen.getByLabelText('Course JSON') as HTMLTextAreaElement).value).toBe(document))
  expect(await screen.findByText('File loaded. Choose Validate and review.')).toBeTruthy()
  expect(mock.fetch).not.toHaveBeenCalled()
})
