'use client'

import { useState } from 'react'
import { apiFetch } from '@/shared/api/client'

type ImportedCourse = {
  title:string; subject:string; objectives:string[];
  lessons:{id:string;title:string;kind:string;explanation:string;question:string;hints:string[];success:string;starter_code?:string;expected_output?:string;requirements?:string[];choices?:string[];answer?:string|number;rubric?:string[]}[]
}

export default function CourseImport({onPublished}:{onPublished:(id:string)=>Promise<void>}) {
  const [text,setText]=useState('')
  const [preview,setPreview]=useState<ImportedCourse|null>(null)
  const [reviewed,setReviewed]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [status,setStatus]=useState('')
  const field='w-full rounded-lg border border-current/20 bg-transparent p-3'
  const button='rounded-lg border border-current/25 px-4 py-2 disabled:opacity-40'
  function change(value:string){setText(value);setPreview(null);setReviewed(false);setError('');setStatus('')}
  async function submit(path:string){
    if(new TextEncoder().encode(text).length>1_000_000)throw new Error('Course file must be at most 1 MB')
    const response=await apiFetch('/api/family-learning/imports/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:text})
    const data=await response.json()
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Could not import this course.')
    return data
  }
  async function action(work:()=>Promise<void>){setBusy(true);setError('');try{await work()}catch(e){setError(e instanceof Error?e.message:'Could not import this course.')}finally{setBusy(false)}}
  return <details className="space-y-3"><summary>Import an AI-prepared course</summary>
    <p className="pt-3">Upload a course JSON file or paste it below. Validation does not save, assign, or run anything. Review every exercise before publishing.</p>
    <label className="block">Course JSON file<input className={field} type="file" accept=".json,application/json" disabled={busy} onChange={event=>{
      const file=event.target.files?.[0]; if(!file)return
      event.currentTarget.value=''
      change('')
      void action(async()=>{if(file.size>1_000_000)throw new Error('Course file must be at most 1 MB');change(await file.text());setStatus('File loaded. Choose Validate and review.')})
    }}/></label>
    <label className="block">Course JSON<textarea rows={8} spellCheck={false} className={field+' font-mono'} disabled={busy} value={text} onChange={event=>change(event.target.value)}/></label>
    <button type="button" className={button} disabled={busy||!text.trim()} onClick={()=>void action(async()=>{
      setPreview(null);setReviewed(false)
      const data=await submit('preview');setPreview(data.course);setStatus('Valid course. Review the content below; nothing has been saved.')
    })}>Validate and review</button>
    {error && <p role="alert">{error}</p>}
    {status && <p role="status">{status}</p>}
    {preview && <section aria-label="Imported course review" className="space-y-4 rounded-lg border border-current/20 p-4">
      <h3 className="text-xl font-semibold">{preview.title}</h3><p>{preview.subject} · {preview.lessons.length} exercises</p>
      <ul>{preview.objectives.map((item,index)=><li key={index}>{item}</li>)}</ul>
      <p>Exercises unlock in the order shown. This review includes private answer keys.</p>
      {preview.lessons.map((lesson,index)=><article key={lesson.id} className="space-y-2 border-t border-current/20 pt-3">
        <h4 className="font-semibold">{index+1}. {lesson.title} ({lesson.kind})</h4>
        <p className="whitespace-pre-wrap">{lesson.explanation}</p><p className="whitespace-pre-wrap">{lesson.question}</p>
        {lesson.choices && <ol>{lesson.choices.map((choice,i)=><li key={i}>{i+1}. {choice}</li>)}</ol>}
        {lesson.answer!==undefined && <p>Correct answer: {lesson.kind==='choice'?lesson.choices?.[Number(lesson.answer)]:lesson.answer}</p>}
        {lesson.kind==='python' && <><p>Starting program</p><pre className="overflow-auto whitespace-pre-wrap">{lesson.starter_code||'(Empty editor)'}</pre><p>Expected printed output</p><pre className="overflow-auto whitespace-pre-wrap">{lesson.expected_output||'(No printed output)'}</pre><p>Required concepts: {lesson.requirements?.join(', ')||'Output only'}</p></>}
        {lesson.rubric && <ul>{lesson.rubric.map((item,i)=><li key={i}>{item}</li>)}</ul>}
        {lesson.hints.map((hint,i)=><p key={i} className="whitespace-pre-wrap">Hint {i+1}: {hint}</p>)}
        <p className="whitespace-pre-wrap">Success feedback: {lesson.success}</p>
      </article>)}
      <label className="block"><input type="checkbox" disabled={busy} checked={reviewed} onChange={event=>setReviewed(event.target.checked)}/> I reviewed the explanations, exercises, hints, and answer expectations.</label>
      <p>Publishing saves a private course. You choose learners separately afterward.</p>
      <button type="button" className={button} disabled={busy||!reviewed} onClick={()=>void action(async()=>{
        const saved=await submit('publish')
        setPreview(null);setText('');setReviewed(false);setStatus('Course published privately. Choose a learner to assign it.')
        await onPublished(saved.id)
      })}>Publish reviewed course</button>
      <button type="button" className={button} disabled={busy} onClick={()=>change('')}>Cancel import</button>
    </section>}
  </details>
}
