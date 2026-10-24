'use client'

import {useEffect,useState} from 'react'
import {apiFetch} from '@/shared/api/client'
import {fieldClass,buttonClass,primaryClass} from './theme'

type Lesson={id:string;title:string;kind:string;explanation:string;question:string;hints:string[];success:string;starter_code?:string;expected_output?:string;requirements?:string[];choices?:string[];answer?:string|number;rubric?:string[]}
type Bundle={document:{format:string;version:number;course:{title:string;subject:string;objectives:string[];lessons:Lesson[]}};solutions:Record<string,string>}
type Draft={id:string;status:string;version:number;brief:{topic:string};bundle:Bundle|null;error:string;published:string}
type Model={model:string;name:string}
const field=fieldClass
const button=buttonClass
async function request<T>(path:string,body?:unknown):Promise<T>{
  const response=await apiFetch('/api/family-learning/authoring'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  const data=await response.json()
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Could not complete this action. Refresh and try again.')
  return data as T
}

export default function CourseAuthoring({onPublished}:{onPublished:(id:string)=>Promise<void>}){
  const [open,setOpen]=useState(false),[models,setModels]=useState<Model[]>([]),[drafts,setDrafts]=useState<Draft[]>([])
  const [draft,setDraft]=useState<Draft|null>(null),[bundle,setBundle]=useState<Bundle|null>(null)
  const [dirty,setDirty]=useState(false),[reviewed,setReviewed]=useState(false),[student,setStudent]=useState(false)
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState(''),[revision,setRevision]=useState('')
  const [brief,setBrief]=useState({topic:'',level:'Beginner, age 9',goals:'',exercises:5,minutes:20,kinds:['python','choice'],instructions:'Use friendly examples and gradual hints.',model:''})
  function select(value:Draft){setDraft(value);setBundle(value.bundle);setDirty(false);setReviewed(false);setStudent(false);setError('');if(value.status==='ready')setBrief(prev=>Object.fromEntries(Object.entries(prev).map(([key,val])=>[key,(value.brief as unknown as Record<string,unknown>)[key]??val])) as typeof prev)}
  async function load(){const [available,items]=await Promise.all([request<{models:Model[]}>('/models'),request<Draft[]>('/drafts')]);setModels(available.models);setDrafts(items);setBrief(prev=>({...prev,model:prev.model||available.models[0]?.model||''}))}
  useEffect(()=>{if(open)void load().catch(e=>setError(e.message))},[open]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{
    if(draft?.status!=='generating')return
    let stopped=false
    const timer=setTimeout(()=>{void request<Draft>('/drafts/'+draft.id).then(value=>{if(!stopped){select(value);if(value.status!=='generating')void load().catch(e=>setError(e.message))}}).catch(e=>{if(!stopped){setError(e.message);setDraft(prev=>prev?{...prev,status:'unconfirmed'}:null)}})},2000)
    return()=>{stopped=true;clearTimeout(timer)}
  },[draft]) // eslint-disable-line react-hooks/exhaustive-deps
  async function action(work:()=>Promise<void>){setBusy(true);setError('');try{await work()}catch(e){setError(e instanceof Error?e.message:'Could not complete this action.')}finally{setBusy(false)}}
  function edit(work:(copy:Bundle)=>void){if(!bundle)return;const copy=structuredClone(bundle);work(copy);setBundle(copy);setDirty(true);setReviewed(false)}
  async function generate(revise=false){
    const id=crypto.randomUUID().replaceAll('-','')
    const saved=await request<{id:string}>('/generate',{...brief,request_id:id,...(revise&&draft?{source:draft.id,source_version:draft.version,instructions:revision}: {})})
    select({id:saved.id,status:'generating',version:1,brief:{topic:brief.topic},bundle:null,error:'',published:''});setStatus('Generating a private draft. You can leave this page and reopen it from Saved drafts.');await load()
  }
  return <section className="space-y-4">
    <button type="button" className={primaryClass} aria-expanded={open} onClick={()=>setOpen(!open)}>Create course with AI</button>
    {open&&<div className="space-y-5 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <p>Use your parent OpenAI connection to prepare a private draft. Only these instructions and a draft you choose to revise are sent. Learner answers and progress stay local. Generation uses your connected account’s allowance.</p>
      {!models.length&&<p>Connect your parent account in <a className="underline" href="/settings/connections">Providers</a>, then refresh drafts.</p>}
      <form className="space-y-3" onSubmit={e=>{e.preventDefault();void action(()=>generate())}}>
        <label className="block">Course topic<input required maxLength={200} className={field} value={brief.topic} onChange={e=>setBrief({...brief,topic:e.target.value})}/></label>
        <label className="block">Age and experience<input required maxLength={200} className={field} value={brief.level} onChange={e=>setBrief({...brief,level:e.target.value})}/></label>
        <label className="block">Learning goals<textarea required maxLength={2000} className={field} value={brief.goals} onChange={e=>setBrief({...brief,goals:e.target.value})}/></label>
        <div className="grid gap-3 sm:grid-cols-2"><label>Number of exercises<input type="number" min={1} max={8} required className={field} value={brief.exercises} onChange={e=>setBrief({...brief,exercises:Number(e.target.value)})}/></label><label>Minutes per exercise<input type="number" min={5} max={60} required className={field} value={brief.minutes} onChange={e=>setBrief({...brief,minutes:Number(e.target.value)})}/></label></div>
        <fieldset className="flex flex-wrap gap-4"><legend>Exercise types</legend>{['python','choice','number','writing'].map(kind=><label key={kind}><input type="checkbox" checked={brief.kinds.includes(kind)} onChange={e=>setBrief({...brief,kinds:e.target.checked?[...brief.kinds,kind]:brief.kinds.filter(k=>k!==kind)})}/> {({python:'Coding',choice:'Multiple choice',number:'Numbers',writing:'Writing'} as Record<string,string>)[kind]}</label>)}</fieldset>
        <label className="block">Parent instructions<textarea maxLength={2000} className={field} value={brief.instructions} onChange={e=>setBrief({...brief,instructions:e.target.value})}/></label>
        <label className="block">Parent model<select className={field} value={brief.model} onChange={e=>setBrief({...brief,model:e.target.value})}>{models.map(item=><option key={item.model} value={item.model}>{item.name}</option>)}</select></label>
        <button className={primaryClass} disabled={busy||dirty||!models.length||!brief.kinds.length||draft?.status==='generating'}>Generate private draft</button>
      </form>
      <button type="button" className={button} disabled={busy} onClick={()=>void action(load)}>Refresh drafts</button>
      <h3 className="font-semibold">Saved drafts</h3><div className="flex flex-wrap gap-2">{drafts.map(item=><button type="button" key={item.id} className={button} disabled={busy||dirty} onClick={()=>select(item)}>{item.bundle?.document.course.title||item.brief.topic} — {item.published?'published':item.status}</button>)}</div>
      {error&&<p role="alert">{error}</p>}{status&&<p role="status">{status}</p>}
      {draft?.status==='generating'&&<p role="status">Preparing your draft… This can take a few minutes. Nothing is published or assigned.</p>}
      {draft?.error&&<p role="alert">{draft.error}</p>}
      {draft?.status==='unconfirmed'&&<button className={button} onClick={()=>void action(async()=>select(await request<Draft>('/drafts/'+draft.id)))}>Check draft status</button>}
      {draft?.status==='ready'&&bundle&&<section aria-label="Generated course review" className="space-y-4">
        <h3 className="text-[15px] font-semibold">Review your course draft</h3>
        <button type="button" className={button} aria-pressed={student} onClick={()=>setStudent(!student)}>{student?'Show parent editor':'Preview student view'}</button>
        {student?<><h4 className="text-xl">{bundle.document.course.title}</h4><p>{bundle.document.course.objectives.join(' · ')}</p><p>Preview of all exercises; the learner unlocks them one at a time. Answers and private reference programs are hidden.</p></>:<>
          <label className="block">Course title<input disabled={!!draft.published||busy} className={field} value={bundle.document.course.title} onChange={e=>edit(copy=>{copy.document.course.title=e.target.value})}/></label>
          <label className="block">Subject<input disabled={!!draft.published||busy} className={field} value={bundle.document.course.subject} onChange={e=>edit(copy=>{copy.document.course.subject=e.target.value})}/></label>
          <label className="block">Objectives (one per line)<textarea disabled={!!draft.published||busy} className={field} value={bundle.document.course.objectives.join('\n')} onChange={e=>edit(copy=>{copy.document.course.objectives=e.target.value.split('\n')})}/></label>
        </>}
        {bundle.document.course.lessons.map((lesson,index)=><article key={lesson.id} className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
          <h4 className="font-semibold">{index+1}. {lesson.title} ({lesson.kind})</h4>
          {student?<><p className="whitespace-pre-wrap">{lesson.explanation}</p><p className="whitespace-pre-wrap">{lesson.question}</p>{lesson.choices?.map((choice,i)=><p key={i}>{i+1}. {choice}</p>)}{lesson.kind==='python'&&<pre className="overflow-auto whitespace-pre-wrap">{lesson.starter_code}</pre>}<details><summary>Prepared hints</summary>{lesson.hints.map((hint,i)=><p key={i}>{hint}</p>)}</details></>:<>
            {(['title','explanation','question','success'] as const).map(key=><label className="block" key={key}>{key}<textarea disabled={!!draft.published||busy} className={field} value={lesson[key]} onChange={e=>edit(copy=>{copy.document.course.lessons[index][key]=e.target.value})}/></label>)}
            <label className="block">Hints (one per line)<textarea disabled={!!draft.published||busy} className={field} value={lesson.hints.join('\n')} onChange={e=>edit(copy=>{copy.document.course.lessons[index].hints=e.target.value.split('\n')})}/></label>
            {lesson.kind==='python'&&<>{(['starter_code','expected_output'] as const).map(key=><label className="block" key={key}>{key==='starter_code'?'Starting program':'Expected printed output'}<textarea disabled={!!draft.published||busy} className={field+' font-mono'} value={lesson[key]||''} onChange={e=>edit(copy=>{copy.document.course.lessons[index][key]=e.target.value})}/></label>)}<label className="block">Private reference solution<textarea disabled={!!draft.published||busy} className={field+' font-mono'} value={bundle.solutions[lesson.id]} onChange={e=>edit(copy=>{copy.solutions[lesson.id]=e.target.value})}/></label><p>Required concepts: {lesson.requirements?.join(', ')||'Output only'}</p></>}
            {lesson.choices&&<label className="block">Choices (one per line)<textarea disabled={!!draft.published||busy} className={field} value={lesson.choices.join('\n')} onChange={e=>edit(copy=>{copy.document.course.lessons[index].choices=e.target.value.split('\n')})}/></label>}
            {lesson.answer!==undefined&&<label className="block">{lesson.kind==='choice'?'Correct choice index (starts at 0)':'Correct numeric answer'}<input disabled={!!draft.published||busy} className={field} value={lesson.answer} onChange={e=>edit(copy=>{copy.document.course.lessons[index].answer=lesson.kind==='choice'?Number(e.target.value):e.target.value})}/></label>}
            {lesson.rubric&&<label className="block">Writing review criteria (one per line)<textarea disabled={!!draft.published||busy} className={field} value={lesson.rubric.join('\n')} onChange={e=>edit(copy=>{copy.document.course.lessons[index].rubric=e.target.value.split('\n')})}/></label>}
          </>}
        </article>)}
        {!draft.published&&<>
          <button type="button" className={button} disabled={busy||!dirty} onClick={()=>void action(async()=>{select(await request<Draft>('/drafts/'+draft.id+'/save',{version:draft.version,bundle}));await load();setStatus('Draft changes saved. Review this version before publishing.')})}>Save draft changes</button>
          {dirty&&<p>Save your changes before revising or publishing.</p>}
          <label className="block">Ask AI to revise this draft<textarea maxLength={2000} className={field} value={revision} onChange={e=>setRevision(e.target.value)}/></label>
          <button type="button" className={button} disabled={busy||dirty||!revision.trim()||!models.length} onClick={()=>void action(()=>generate(true))}>Generate revised draft</button>
          <p>Revisions create a separate draft and preserve this version.</p>
          <label className="block"><input type="checkbox" checked={reviewed} disabled={busy||dirty} onChange={e=>setReviewed(e.target.checked)}/> I reviewed this course’s facts, difficulty, hints, and answer expectations.</label>
          <p>Publication tests every private Python solution in the isolated sandbox. Publishing saves a private course; assignment is a separate step.</p>
          <button type="button" className={primaryClass} disabled={busy||dirty||!reviewed} onClick={()=>void action(async()=>{setStatus('Checking reference programs and publishing…');const saved=await request<{id:string}>('/drafts/'+draft.id+'/publish',{version:draft.version,reviewed:true});setDraft({...draft,published:saved.id});setReviewed(false);await load();await onPublished(saved.id);setStatus('Course published privately. Choose a learner to assign it.')})}>Check and publish reviewed course</button>
        </>}
        {draft.published&&<p>Published privately. Assignment is managed in the course below.</p>}
      </section>}
    </div>}
  </section>
}
