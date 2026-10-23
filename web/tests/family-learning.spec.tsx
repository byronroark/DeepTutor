import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import FamilyLearningPage from '@/app/family-learning/page'

const mock = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('@/shared/api/client', () => ({apiFetch: mock.fetch}))
const course = {title:'Fractions',subject:'Math',objectives:['Understand halves'],lessons:[
  {id:'half',title:'One half',explanation:'Two equal shares.',question:'Which is half?',kind:'choice',choices:['1/2','1/4'],unlocked:true,state:'new'},
  {id:'next',title:'The next step',unlocked:false},
]}
const response = (data: unknown, ok=true) => ({ok,json:async()=>data})

beforeEach(()=>vi.clearAllMocks())

it('starts a fresh attempt after the broker reports an interrupted run',async()=>{
  const ids:string[]=[]
  mock.fetch.mockImplementation(async(path:string,init?:RequestInit)=>{
    if(path.endsWith('/python')){
      ids.push(JSON.parse(String(init?.body)).request_id)
      return ids.length===1?response({detail:'This run was interrupted. Run again to start a new attempt.'},false):response({state:'passed',feedback:'Recovered!',output:'7\n',execution:'finished'})
    }
    if(path.endsWith('/courses/python-a'))return response({title:'Python lab',subject:'Python',objectives:[],lessons:[{id:'program',title:'Stars',question:'Print 7.',kind:'python',starter_code:'print(7)',unlocked:true,state:'new'}]})
    return response({role:'learner',courses:[{id:'python-a',title:'Python lab',subject:'Python'}]})
  })
  render(<FamilyLearningPage/>)
  fireEvent.click(await screen.findByRole('button',{name:'Python lab'}))
  fireEvent.click(await screen.findByRole('button',{name:'Run Python exercise'}))
  expect(await screen.findByText('This run was interrupted. Run again to start a new attempt.')).toBeTruthy()
  await waitFor(()=>expect(screen.getByRole('button',{name:'Run Python exercise'}).hasAttribute('disabled')).toBe(false))
  fireEvent.click(screen.getByRole('button',{name:'Run Python exercise'}))
  expect(await screen.findByText('Recovered!')).toBeTruthy()
  expect(ids).toHaveLength(2)
  expect(ids[0]).not.toBe(ids[1])
})

it('lets a learner answer, see prepared feedback and unlock the next exercise',async()=>{
  let answered=false
  mock.fetch.mockImplementation(async(path:string,init?:RequestInit)=>{
    if(path.endsWith('/answer')) {answered=true;expect(JSON.parse(String(init?.body)).answer).toBe('0');return response({feedback:'Exactly right!'})}
    if(path.endsWith('/courses/course-a')) return response(answered?{...course,lessons:[{...course.lessons[0],state:'passed'}, {...course.lessons[1],unlocked:true,kind:'number',question:'How many pieces?'}]}:course)
    return response({role:'learner',courses:[{id:'course-a',title:'Fractions',subject:'Math'}]})
  })
  render(<FamilyLearningPage/>)
  fireEvent.click(await screen.findByRole('button',{name:'Fractions'}))
  expect(await screen.findByText('Finish the earlier lesson to unlock this step.')).toBeTruthy()
  fireEvent.click(screen.getByLabelText('1/2'))
  fireEvent.click(screen.getByRole('button',{name:'Check my answer'}))
  expect(await screen.findByText('Exactly right!')).toBeTruthy()
  expect(screen.getByText('Completed ✓')).toBeTruthy()
  expect(screen.getByText('How many pieces?')).toBeTruthy()
  expect(screen.queryByText('Prepare lessons')).toBeNull()
})

it('keeps writing feedback with the parent and requires feedback before approval',async()=>{
  mock.fetch.mockImplementation(async(path:string,init?:RequestInit)=>{
    if(path.endsWith('/learners'))return response([{id:'child',username:'Learner'}])
    if(path.endsWith('/review')){expect(JSON.parse(String(init?.body))).toEqual({approve:false,feedback:'Add an example.'});return response({saved:true})}
    if(path.endsWith('/courses/course-a'))return response({course,assignments:[],progress:[],submissions:[{id:'draft-a',learner:'child',writing:'My report.',decision:'pending',feedback:''}]})
    return response({role:'parent',courses:[{id:'course-a',title:'Fractions',subject:'Math'}]})
  })
  render(<FamilyLearningPage/>)
  fireEvent.click(await screen.findByRole('button',{name:'Fractions'}))
  expect(await screen.findByText('My report.')).toBeTruthy()
  expect(screen.getByRole('button',{name:'Approve writing'}).hasAttribute('disabled')).toBe(true)
  fireEvent.change(screen.getByLabelText('Your feedback'),{target:{value:'Add an example.'}})
  fireEvent.click(screen.getByRole('button',{name:'Request a revision'}))
  await waitFor(()=>expect(screen.getByText('Feedback saved for your learner.')).toBeTruthy())
})

it('shows an actionable sign-in message without displaying private lessons',async()=>{
  mock.fetch.mockResolvedValue(response({detail:'A signed-in account is required'},false))
  render(<FamilyLearningPage/>)
  expect(await screen.findByText('A signed-in account is required')).toBeTruthy()
  expect(screen.getByRole('link',{name:'Sign in to your account'})).toBeTruthy()
  expect(screen.queryByRole('button',{name:'Fractions'})).toBeNull()
})

it('runs assigned Python through the narrow endpoint and displays output',async()=>{
  let passed=false
  mock.fetch.mockImplementation(async(path:string,init?:RequestInit)=>{
    if(path.endsWith('/draft')){
      expect(JSON.parse(String(init?.body)).text).toBe('stars = 5\nprint(stars + 2)')
      return response({saved:true})
    }
    if(path.endsWith('/python')){
      const body=JSON.parse(String(init?.body))
      expect(body.code).toBe('stars = 5\nprint(stars + 2)')
      expect(body.learner).toBeUndefined()
      expect(body.request_id).toMatch(/^[a-f0-9]{32}$/)
      passed=true
      return response({state:'passed',feedback:'Your program worked!',output:'7\n',execution:'finished'})
    }
    if(path.endsWith('/courses/python-a'))return response({title:'Python lab',subject:'Python',objectives:['Use variables'],lessons:[{id:'program',title:'Stars',explanation:'Use a variable.',question:'Print 7.',kind:'python',starter_code:'stars = 5\nprint(stars + 2)',unlocked:true,state:passed?'passed':'new'}]})
    return response({role:'learner',courses:[{id:'python-a',title:'Python lab',subject:'Python'}]})
  })
  render(<FamilyLearningPage/>)
  fireEvent.click(await screen.findByRole('button',{name:'Python lab'}))
  expect(await screen.findByLabelText('Your Python program')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'Save program'}))
  expect(await screen.findByText('Program saved on this computer.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button',{name:'Run Python exercise'}))
  expect(await screen.findByText('Your program worked!')).toBeTruthy()
  expect(screen.getByLabelText('Program result').textContent).toContain('7')
  expect(screen.getByText('Completed ✓')).toBeTruthy()
})
