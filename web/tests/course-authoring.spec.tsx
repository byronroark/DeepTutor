import React from 'react'
import {fireEvent,render,screen,waitFor} from '@testing-library/react'
import {beforeEach,expect,it,vi} from 'vitest'
import CourseAuthoring from '@/app/family-learning/CourseAuthoring'
const mock=vi.hoisted(()=>({fetch:vi.fn()}))
vi.mock('@/shared/api/client',()=>({apiFetch:mock.fetch}))
const bundle={document:{format:'family-learning-course',version:1,course:{title:'Count stars',subject:'Python',objectives:['Use variables'],lessons:[{id:'stars',title:'Stars',kind:'python',explanation:'A variable stores a value.',question:'Print 7.',hints:['Try print.'],success:'Good work!',starter_code:'stars = 5',expected_output:'7\n',requirements:['assignment']}]}},solutions:{stars:'stars = 5\nprint(stars + 2)'}}
const draft={id:'abc',status:'ready',version:1,brief:{topic:'Stars'},bundle,error:'',published:''}
beforeEach(()=>{vi.clearAllMocks();mock.fetch.mockImplementation(async(path:string)=>({ok:true,json:async()=>path.endsWith('/models')?{models:[{model:'test',name:'Parent model'}]}:path.endsWith('/drafts')?[draft]:path.endsWith('/generate')?{id:'new'}:path.endsWith('/publish')?{id:'course'}:{...draft,version:2}}))})
async function open(){render(<CourseAuthoring onPublished={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'Create course with AI'}));await screen.findByRole('option',{name:'Parent model'})}
it('sends only the parent brief and creates a private pending draft',async()=>{
 await open();fireEvent.change(screen.getByLabelText('Course topic'),{target:{value:'Planets'}});fireEvent.change(screen.getByLabelText('Learning goals'),{target:{value:'Count planets'}})
 fireEvent.click(screen.getByRole('button',{name:'Generate private draft'}));await screen.findByText(/Preparing your draft/)
 const call=mock.fetch.mock.calls.find(([path])=>path.endsWith('/generate'));expect(call).toBeTruthy();const body=JSON.parse(call![1].body)
 expect(body.topic).toBe('Planets');expect(body.request_id).toMatch(/^[a-f0-9]{32}$/);expect(body).not.toHaveProperty('learner')
 expect(mock.fetch.mock.calls.some(([path])=>path.includes('/publish')||path.includes('/assignment'))).toBe(false)
})
it('keeps private solutions out of the student preview and requires review before publishing',async()=>{
 await open();fireEvent.click(await screen.findByRole('button',{name:'Count stars — ready'}))
 expect(screen.getByRole('button',{name:'Check and publish reviewed course'})).toBeDisabled()
 expect(screen.getByLabelText('Private reference solution')).toHaveValue('stars = 5\nprint(stars + 2)')
 fireEvent.click(screen.getByRole('button',{name:'Preview student view'}));expect(screen.queryByLabelText('Private reference solution')).toBeNull();expect(screen.getByText('Print 7.')).toBeTruthy()
 fireEvent.click(screen.getByLabelText('I reviewed this course’s facts, difficulty, hints, and answer expectations.'))
 fireEvent.click(screen.getByRole('button',{name:'Check and publish reviewed course'}))
 await screen.findByText('Published privately. Assignment is managed in the course below.')
 expect(mock.fetch.mock.calls.some(([path])=>path.includes('/assignment'))).toBe(false)
})
it('edits invalidate review and require an explicit save',async()=>{
 await open();fireEvent.click(await screen.findByRole('button',{name:'Count stars — ready'}));fireEvent.click(screen.getByLabelText('I reviewed this course’s facts, difficulty, hints, and answer expectations.'))
 fireEvent.change(screen.getByLabelText('Course title'),{target:{value:'More stars'}})
 expect(screen.getByRole('button',{name:'Check and publish reviewed course'})).toBeDisabled()
 fireEvent.click(screen.getByRole('button',{name:'Save draft changes'}))
 await screen.findByText('Draft changes saved. Review this version before publishing.')
 const call=mock.fetch.mock.calls.find(([path])=>path.endsWith('/save'));expect(JSON.parse(call![1].body).bundle.document.course.title).toBe('More stars')
})
it('shows sandbox failures and keeps the draft unpublished',async()=>{
 await open();fireEvent.click(await screen.findByRole('button',{name:'Count stars — ready'}));fireEvent.click(screen.getByLabelText('I reviewed this course’s facts, difficulty, hints, and answer expectations.'))
 mock.fetch.mockResolvedValueOnce({ok:false,json:async()=>({detail:'Reference solution output does not match'})})
 fireEvent.click(screen.getByRole('button',{name:'Check and publish reviewed course'}))
 expect(await screen.findByRole('alert')).toHaveTextContent('Reference solution output does not match')
 expect(screen.queryByText('Published privately. Assignment is managed in the course below.')).toBeNull()
})
it('revises from a saved draft without overwriting it',async()=>{
 await open();fireEvent.click(await screen.findByRole('button',{name:'Count stars — ready'}));fireEvent.change(screen.getByLabelText('Ask AI to revise this draft'),{target:{value:'Use planets instead'}})
 fireEvent.click(screen.getByRole('button',{name:'Generate revised draft'}));await waitFor(()=>expect(mock.fetch.mock.calls.some(([path])=>path.endsWith('/generate'))).toBe(true))
 const call=mock.fetch.mock.calls.find(([path])=>path.endsWith('/generate'));expect(JSON.parse(call![1].body)).toMatchObject({source:'abc',source_version:1,instructions:'Use planets instead'})
 expect(mock.fetch.mock.calls.some(([path])=>path.endsWith('/save'))).toBe(false)
})
