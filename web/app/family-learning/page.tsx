'use client'

import {randomUuid} from '@/lib/random-uuid'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '@/shared/api/client'
import {fieldClass,buttonClass,primaryClass} from './theme'
import CourseImport from './CourseImport'
import FamilyFrame from './FamilyFrame'
import PythonEditor from './PythonEditor'
import {PageHeader,pageGridClass} from '@/components/layout/FeaturePage'
import CourseAuthoring from './CourseAuthoring'
import { AttemptHistory, RetakeControls, type HistoryEntry } from './Retakes'

type Summary = { id: string; title: string; subject: string }
type Lesson = { id: string; title: string; explanation?: string; question?: string; kind?: string; choices?: string[]; rubric?: string[]; answer?: string | number; hints?: string[]; success?: string; starter_code?: string; expected_output?: string; requirements?: string[]; unlocked?: boolean; state?: string; feedback?: string; draft?: string; attempts?:number }
type Execution = {state:string;feedback:string;execution:string;output:string}
type Course = { title: string; subject: string; objectives: string[]; lessons: Lesson[]; attempt_epoch?:number; history?:HistoryEntry[] }
type Submission = { id: string; learner: string; writing: string; decision: string; feedback: string }
type ParentCourse = { course: Course; assignments: { learner: string; active: number; epoch?:number }[]; submissions: Submission[]; progress: {learner: string; lesson: string; state: string; attempts: number}[]; history?:HistoryEntry[] }
type Account = { id: string; username: string }
const base = '/api/family-learning'

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await apiFetch(base + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save. Please try again.')
  return data as T
}

export default function FamilyLearningPage() {
  const [role, setRole] = useState('')
  const [courses, setCourses] = useState<Summary[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [selected, setSelected] = useState('')
  const [course, setCourse] = useState<Course | null>(null)
  const [parentCourse, setParentCourse] = useState<ParentCourse | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [feedback, setFeedback] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('Loading your lessons…')
  const [busy, setBusy] = useState(false)
  const [exerciseType, setExerciseType] = useState('number')
  const [executions,setExecutions] = useState<Record<string,Execution>>({})
  const pendingRuns = useRef<Record<string,{code:string;id:string}>>({})
  const attemptEpochs = useRef<Record<string,number>>({})
  const [codingHints,setCodingHints] = useState<Record<string,{items:string[];more:boolean}>>({})
  const load = useCallback(async () => {
    const overview = await request<{role: string; courses: Summary[]; learner_host?:boolean}>('')
    setRole(overview.role); setCourses(overview.courses)
    if (overview.role === 'parent') setAccounts(await request<Account[]>('/learners'))
  }, [])
  useEffect(() => { void load().then(()=>setMessage('Your work stays on this computer.')).catch(error=>setMessage(error.message)) }, [load])

  async function open(id: string) {
    const data = await request<Course | ParentCourse>(`/courses/${id}`)
    setSelected(id)
    if ('course' in data) { setParentCourse(data); setCourse(data.course) }
    else {
      if(attemptEpochs.current[id]!==(data.attempt_epoch??0)){setExecutions({});setCodingHints({});pendingRuns.current={}}
      attemptEpochs.current[id]=data.attempt_epoch??0
      setParentCourse(null); setCourse(data); setAnswers(Object.fromEntries(data.lessons.map(item => [item.id, item.draft || item.starter_code || ''])))
    }
  }
  async function action(work: () => Promise<void>) {
    setBusy(true)
    try { await work() } catch (error) { setMessage(error instanceof Error ? error.message : 'Something went wrong.') }
    finally { setBusy(false) }
  }
  const field = fieldClass
  const button = buttonClass
  const name = (id: string) => accounts.find(account=>account.id===id)?.username ?? 'Learner'
  return <FamilyFrame role={role}>
    <PageHeader title="Family Learning" description="Small steps. Time to practise. Help when you need it." action={<>
      {role==='parent' && <a className={button} href="/">DeepTutor dashboard</a>}
      {role && <button className={button} disabled={busy} onClick={()=>void action(async()=>{
        const response=await apiFetch('/api/auth/logout',{method:'POST'})
        if(!response.ok)throw new Error('Could not sign out. Please try again.')
        window.location.assign('/login?next=%2Ffamily-learning')
      })}>Sign out</button>}
    </>}/>
    <p className="rounded-lg border border-[var(--border)] bg-[var(--muted)] px-4 py-3" role="status" aria-live="polite">{message}</p>
    {!role && <a href="/login">Sign in to your account</a>}
    <section aria-label="Your courses" className="space-y-3">
      <div className="flex items-center justify-between gap-3"><h2 className="text-[13.5px] font-semibold">{role==='parent'?'Course library':'Your courses'}</h2><span className="text-xs text-[var(--muted-foreground)]">{courses.length} {courses.length===1?'course':'courses'}</span></div>
      <div className={pageGridClass(3)}>{courses.map(item => <button aria-label={item.title} aria-pressed={selected===item.id} className={'group min-h-24 rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-50 '+(selected===item.id?'border-[var(--primary)] bg-[var(--accent)]':'border-[var(--border)] bg-[var(--card)] hover:bg-[var(--muted)]')} disabled={busy} key={item.id} onClick={() => void action(() => open(item.id))}><span className="block font-medium">{item.title}</span><span className="mt-1.5 block text-xs text-[var(--muted-foreground)]">{item.subject}</span></button>)}</div>
      {role && courses.length===0 && <p className="rounded-xl border border-dashed border-[var(--border)] p-6 text-[var(--muted-foreground)]">{role==='parent'?'Prepare your first course below, then assign it when you are ready.':'Your assigned courses will appear here.'}</p>}
    </section>
    {role === 'parent' && <section className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
      <h2 className="text-[15px] font-semibold">Prepare lessons</h2>
      {<CourseAuthoring onPublished={async(id)=>{await load();await open(id);setMessage('AI-prepared course published privately. Choose a learner to assign it.')}}/>}
      <p>{"Add the starter lessons, review their material, then assign them individually."}</p>
      <CourseImport onPublished={async(id)=>{await load();await open(id);setMessage('Course imported privately. Review it and choose a learner to assign it.')}}/>
      <button className={button} disabled={busy} onClick={() => void action(async () => {
        for (const starter of await request<Course[]>('/starters')) await request('/courses', starter)
        await load(); setMessage('Starter lessons added for review. Nothing was assigned automatically.')
      })}>Add starter lessons for review</button>
      <details><summary>Create a lesson</summary><form className="space-y-3 pt-3" onSubmit={event=>{
        event.preventDefault()
        const form=new FormData(event.currentTarget)
        const text=(key:string)=>String(form.get(key)??'').trim()
        void action(async()=>{
          const lesson={id:'first-step',title:text('title'),explanation:text('explanation'),question:text('question'),kind:exerciseType,
            hints:[text('hint')||'Review the explanation or ask your parent for help.'],success:text('success')||'Well done!',
            ...(exerciseType==='number'?{answer:text('answer')}:{}),
            ...(exerciseType==='choice'?{choices:text('choices').split('\n').map(value=>value.trim()).filter(Boolean),answer:Number(text('correct'))-1}:{}),
            ...(exerciseType==='writing'?{rubric:text('rubric').split('\n').map(value=>value.trim()).filter(Boolean)}:{}),
            ...(exerciseType==='python'?{starter_code:String(form.get('starter_code')??''),expected_output:String(form.get('expected_output')??''),requirements:text('requirement')?[text('requirement')]:[]}:{})}
          const saved=await request<{id:string}>('/courses',{title:text('title'),subject:text('subject'),objectives:[text('objective')],lessons:[lesson]})
          await load();await open(saved.id);setMessage('Lesson saved for review. Assign it when you are ready.')
        })
      }}>
        {[['title','Lesson title'],['subject','Subject'],['objective','Learning objective']].map(([key,label])=><label className="block" key={key}>{label}<input name={key} required maxLength={200} className={field}/></label>)}
        <label className="block">Explanation<textarea name="explanation" required maxLength={20000} className={field}/></label>
        <label className="block">Question<textarea name="question" required maxLength={20000} className={field}/></label>
        <label className="block">Exercise type<select value={exerciseType} onChange={event=>setExerciseType(event.target.value)} className={field}><option value="number">Number answer</option><option value="choice">Multiple choice</option><option value="writing">Writing for parent review</option><option value="python">Python program</option></select></label>
        {exerciseType==='number' && <label className="block">Correct number<input name="answer" required maxLength={100} className={field}/></label>}
        {exerciseType==='choice' && <><label className="block">Choices, one per line<textarea name="choices" required className={field}/></label><label className="block">Correct choice number (starting at 1)<input name="correct" required type="number" min="1" max="8" className={field}/></label></>}
        {exerciseType==='writing' && <label className="block">Review criteria, one per line<textarea name="rubric" required className={field}/></label>}
        {exerciseType==='python' && <>
          <label className="block">Starting program<textarea name="starter_code" maxLength={16384} spellCheck={false} className={field+' font-mono'}/></label>
          <label className="block">Expected printed output<textarea name="expected_output" maxLength={8192} spellCheck={false} className={field+' font-mono'}/></label>
          <label className="block">Required concept<select name="requirement" className={field}><option value="">Output only</option><option value="assignment">A variable assignment</option><option value="for_loop">A for loop</option><option value="while_loop">A while loop</option></select></label>
        </>}
        <label className="block">Prepared hint<textarea name="hint" maxLength={2000} className={field}/></label>
        <label className="block">Success feedback<input name="success" maxLength={2000} className={field}/></label>
        <button className={primaryClass} disabled={busy}>Save for review</button>
      </form></details>
    </section>}
    {course && <section className="space-y-4"><h2 className="font-serif text-2xl font-semibold">{course.title}</h2><ul>{course.objectives.map(item=><li key={item}>{item}</li>)}</ul>
      {parentCourse && <>
        <button className={button} disabled={busy} onClick={()=>void action(async()=>{
          const response=await apiFetch(`/api/family-learning/courses/${selected}/export`)
          if(!response.ok)throw new Error('Could not download this course.')
          const url=URL.createObjectURL(await response.blob())
          const link=document.createElement('a');link.href=url;link.download='family-learning-course.json';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)
          setMessage('Course downloaded. Import it on the learner PC, review it, then assign it separately.')
        })}>Download course for learner PC</button>
        <h3 className="font-semibold">Assignments</h3>
        {accounts.map(account => {const active=parentCourse.assignments.some(item=>item.learner===account.id && item.active===1); return <button disabled={busy} className={button} key={account.id} onClick={()=>void action(async()=>{
          await request(`/courses/${selected}/assignment`,{learner:account.id,active:!active}); await open(selected); setMessage(active?'Assignment removed.':'Lesson assigned.')
        })}>{active?'Remove assignment for':'Assign to'} {account.username}</button>})}
        <h3 className="font-semibold">Progress</h3>
        {parentCourse.progress.map(item=><p key={item.learner+item.lesson}>{name(item.learner)} · {item.lesson}: {item.state} ({item.attempts} attempts)</p>)}
        <RetakeControls key={selected} course={selected} assignments={parentCourse.assignments} lessons={course.lessons} name={name} onSaved={async()=>{await open(selected)}}/>
        <h3 className="font-semibold">Writing review</h3>
        {parentCourse.submissions.map(item=><article key={item.id} className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
          <p>{name(item.learner)} · {item.decision}</p><pre className="whitespace-pre-wrap font-sans">{item.writing}</pre>
          {item.decision==='pending'?<><label className="block">Your feedback<textarea className={field} value={feedback[item.id]??''} onChange={event=>setFeedback({...feedback,[item.id]:event.target.value})}/></label>
            {[false,true].map(approve=><button key={String(approve)} className={button} disabled={busy || !feedback[item.id]?.trim()} onClick={()=>void action(async()=>{
              await request(`/submissions/${item.id}/review`,{approve,feedback:feedback[item.id]}); await open(selected); setMessage('Feedback saved for your learner.')
            })}>{approve?'Approve writing':'Request a revision'}</button>)}</>:<p>{item.feedback}</p>}
        </article>)}
      </>}
      <AttemptHistory entries={parentCourse?.history??course.history??[]} lessons={course.lessons} name={parentCourse?name:undefined}/>
      {course.lessons.map(lesson=><article key={selected+lesson.id} className={'space-y-3 rounded-xl border bg-[var(--card)] p-5 '+(lesson.state==='passed'?'border-[var(--success)] border-l-4':'border-[var(--border)]')}>
        <h3 className="text-[15px] font-semibold">{lesson.title}</h3>
        {lesson.unlocked===false?<p>Finish the earlier lesson to unlock this step.</p>:<>
          <p className="whitespace-pre-wrap">{lesson.explanation}</p><p className="font-semibold">{lesson.question}</p>
          {lesson.rubric && <ul>{lesson.rubric.map(item=><li key={item}>{item}</li>)}</ul>}
          {role==='parent' && <aside className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
            <h4 className="font-semibold">Parent review</h4>
            {lesson.choices && <ol>{lesson.choices.map((choice,index)=><li key={index}>{index+1}. {choice}</li>)}</ol>}
            {lesson.answer!==undefined && <p>Correct answer: {lesson.kind==='choice'?lesson.choices?.[Number(lesson.answer)]:String(lesson.answer)}</p>}
            {lesson.kind==='python' && <><p>Expected printed output:</p><pre className="whitespace-pre-wrap">{lesson.expected_output}</pre><p>Required concepts: {lesson.requirements?.join(', ')||'Output only'}</p></>}
            {lesson.hints?.map((hint,index)=><p key={index}>Hint {index+1}: {hint}</p>)}
            <p>Success feedback: {lesson.success}</p>
          </aside>}
          {role==='learner' && <>
            {lesson.state==='passed'?<p className="inline-flex items-center rounded-full border border-[var(--success)] bg-[var(--success-surface)] px-3 py-1 text-sm font-semibold text-[var(--success-foreground)]">Completed ✓</p>:lesson.state==='review'?<p>Your parent is reviewing this. Your writing is saved.</p>:<>
              {lesson.kind==='choice'?<fieldset><legend>Choose your answer</legend>{lesson.choices?.map((choice,index)=><label key={index} className="block p-2"><input type="radio" name={lesson.id} checked={answers[lesson.id]===String(index)} onChange={()=>setAnswers({...answers,[lesson.id]:String(index)})}/> {choice}</label>)}</fieldset>:
                <label className="block">{lesson.kind==='python'?'Your Python program':'Your answer'}{lesson.kind==='python'?<PythonEditor disabled={busy} value={answers[lesson.id]??''} onChange={value=>setAnswers({...answers,[lesson.id]:value})}/>:<textarea disabled={busy} className={field} rows={4} maxLength={20000} value={answers[lesson.id]??''} onChange={event=>setAnswers({...answers,[lesson.id]:event.target.value})}/>}</label>}
              {['writing','python'].includes(lesson.kind??'') && <button className={button} disabled={busy} onClick={()=>void action(async()=>{await request(`/courses/${selected}/lessons/${lesson.id}/draft`,{text:answers[lesson.id]??''});setMessage(lesson.kind==='python'?'Program saved on this computer.':'Draft saved on this computer.')})}>{lesson.kind==='python'?'Save program':'Save draft'}</button>}
              {lesson.kind==='python' && <button className={button} disabled={busy || codingHints[selected+':'+lesson.id]?.more===false} onClick={()=>void action(async()=>{
                const key=selected+':'+lesson.id,items=codingHints[key]?.items??[]
                const result=await request<{hint:string;has_more:boolean}>(`/courses/${selected}/lessons/${lesson.id}/hint?index=${items.length}`)
                setCodingHints(previous=>({...previous,[key]:{items:[...items,result.hint],more:result.has_more}}))
              })}>{codingHints[selected+':'+lesson.id]?.more===false?'All hints shown':codingHints[selected+':'+lesson.id]?'Next hint':'Show hint'}</button>}
              <button className={primaryClass} disabled={busy || !answers[lesson.id]?.trim()} onClick={()=>void action(async()=>{
                if(lesson.kind==='python'){
                  setMessage('Running your program…')
                  const key=selected+':'+lesson.id,code=answers[lesson.id]
                  const pending=pendingRuns.current[key]
                  const id=pending?.code===code?pending.id:randomUuid().replaceAll('-','')
                  pendingRuns.current[key]={code,id}
                  let result:Execution
                  try {result=await request<Execution>(`/courses/${selected}/lessons/${lesson.id}/python`,{code,request_id:id})}
                  catch(error){if(error instanceof Error && (error.message.includes('This run was interrupted.')||error.message.includes('earlier attempt')))delete pendingRuns.current[key];throw error}
                  delete pendingRuns.current[key]
                  setExecutions(previous=>({...previous,[key]:result}));await open(selected);setMessage(result.feedback)
                  return
                }
                const result=await request<{feedback:string}>(`/courses/${selected}/lessons/${lesson.id}/answer`,{answer:answers[lesson.id],request_id:randomUuid().replaceAll('-','')}); await open(selected);setMessage(result.feedback)
              })}>{lesson.kind==='writing'?'Send to parent':lesson.kind==='python'?'Run Python exercise':'Check my answer'}</button>
            </>}
            {lesson.feedback && <p role="status" className={lesson.state==='passed'?'rounded-lg border-l-4 border-[var(--success)] bg-[var(--success-surface)] p-4 font-medium text-[var(--success-foreground)]':'text-[var(--muted-foreground)]'}>{lesson.feedback}</p>}
            {!!lesson.attempts && <p>Tries this attempt: {lesson.attempts}</p>}
            {codingHints[selected+':'+lesson.id] && <aside aria-label="Coding hints" role="note" className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">{codingHints[selected+':'+lesson.id].items.map((hint,index)=><p key={index}>Hint {index+1}: {hint}</p>)}</aside>}
            {executions[selected+':'+lesson.id] && <section aria-label="Program result" className={lesson.state==='passed'?'text-[var(--success)]':''}><p className="font-medium">{({finished:'Program finished',error:'Check your program',time_limit:'Time limit reached — try a smaller loop',output_limit:'Too much printed output — try a smaller loop',syntax_feedback:'Check your Python syntax'} as Record<string,string>)[executions[selected+':'+lesson.id].execution]||'Program result'}</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">{executions[selected+':'+lesson.id].output||'(No printed output)'}</pre></section>}
          </>}
        </>}
      </article>)}
    </section>}
    <button className={button} disabled={busy} onClick={()=>void action(async()=>{await load();if(selected)await open(selected)})}>Refresh</button>
  </FamilyFrame>
}
