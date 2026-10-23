'use client'

import { useState } from 'react'
import { apiFetch } from '@/shared/api/client'

export type HistoryEntry={id:string;learner:string;scope:string;archived_at:string;results:{lesson:string;state:string;attempts:number;feedback:string}[]}

export function AttemptHistory({entries,lessons,name}:{entries:HistoryEntry[];lessons:{id:string;title:string}[];name?:(id:string)=>string}){
  if(!entries.length)return null
  const title=(id:string)=>lessons.find(item=>item.id===id)?.title??id
  return <section aria-label="Previous results" className="space-y-3"><h3 className="text-xl font-semibold">Previous results</h3>
    <p>Earlier results stay saved. Compare completion and number of tries; these lessons do not currently use numeric grades.</p>
    {entries.map(entry=><details key={entry.id} className="rounded-lg border border-current/20 p-3">
      <summary>{name?name(entry.learner)+' · ':''}{entry.scope==='*'?'Course retake':title(entry.scope)} · {new Date(entry.archived_at).toLocaleString()}</summary>
      {entry.results.length===0?<p>No completed result was recorded before this retake.</p>:entry.results.map(result=><article key={result.lesson} className="py-2">
        <h4 className="font-semibold">{title(result.lesson)}</h4><p>{result.state} · {result.attempts} {result.attempts===1?'try':'tries'}</p><p className="whitespace-pre-wrap">{result.feedback}</p>
      </article>)}
    </details>)}
  </section>
}

export function RetakeControls({course,assignments,lessons,name,onSaved}:{course:string;assignments:{learner:string;active:number;epoch?:number}[];lessons:{id:string;title:string}[];name:(id:string)=>string;onSaved:()=>Promise<void>}){
  const [learner,setLearner]=useState('')
  const [lesson,setLesson]=useState('')
  const [confirm,setConfirm]=useState(false)
  const [busy,setBusy]=useState(false)
  const [message,setMessage]=useState('')
  const [pending,setPending]=useState<{id:string;epoch:number}|null>(null)
  const active=assignments.filter(item=>item.active===1)
  const selected=active.find(item=>item.learner===learner)
  const field='w-full rounded-lg border border-current/20 bg-transparent p-3'
  const button='rounded-lg border border-current/25 px-4 py-2 disabled:opacity-40'
  return <section className="space-y-3 rounded-lg border border-current/20 p-4" aria-label="Start a retake">
    <h3 className="text-xl font-semibold">Start a retake</h3>
    <p>Parent only. Preserve the current results, then start the selected lesson or whole course again. Retaking a lesson locks later lessons until it is passed again; their existing results are preserved.</p>
    <label className="block">Learner for retake<select disabled={busy} className={field} value={learner} onChange={e=>{setLearner(e.target.value);setConfirm(false);setPending(null);setMessage('')}}><option value="">Choose an assigned learner</option>{active.map(item=><option key={item.learner} value={item.learner}>{name(item.learner)}</option>)}</select></label>
    <label className="block">What to retake<select disabled={busy} className={field} value={lesson} onChange={e=>{setLesson(e.target.value);setConfirm(false);setPending(null);setMessage('')}}><option value="">Whole course</option>{lessons.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
    <label className="block"><input type="checkbox" disabled={busy} checked={confirm} onChange={e=>setConfirm(e.target.checked)}/> Preserve previous results and start a fresh attempt.</label>
    <button className={button} disabled={busy||!selected||!confirm} onClick={()=>void(async()=>{
      if(!selected)return
      setBusy(true);setMessage('')
      const operation=pending??{id:crypto.randomUUID().replaceAll('-',''),epoch:selected.epoch??0};setPending(operation)
      try{
        const response=await apiFetch(`/api/family-learning/courses/${course}/retake`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({learner,lesson:lesson||null,expected_epoch:operation.epoch,request_id:operation.id})})
        const data=await response.json()
        if(!response.ok){if(response.status<500)setPending(null);throw new Error(typeof data.detail==='string'?data.detail:'Could not start the retake.')}
        setConfirm(false);setPending(null);await onSaved();setMessage('Retake started. Previous results are saved. The learner should refresh their course.')
      }catch(error){setMessage(error instanceof Error?error.message:'Could not confirm the retake. Try again to check the same request.')}finally{setBusy(false)}
    })()}>{busy?'Starting retake…':lesson?'Retake lesson':'Retake course'}</button>
    {message && <p role="status">{message}</p>}
  </section>
}
