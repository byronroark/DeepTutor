'use client'
import {useEffect,useState} from 'react'
import {apiFetch} from '@/shared/api/client'
import {randomUuid} from '@/lib/random-uuid'
import {fieldClass,buttonClass,primaryClass} from './theme'
type Topic={id:string;learner:string;topic:string;created:number;status:string;approved_topic:string}
async function request<T>(path:string,body?:unknown):Promise<T>{
 const r=await apiFetch('/api/family-learning/topic-requests'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
 const value=await r.json();if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'Could not update topic requests');return value
}
export default function TopicRequests({role}:{role:string}){
 const [items,setItems]=useState<Topic[]>([]),[text,setText]=useState(''),[edits,setEdits]=useState<Record<string,string>>({}),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const load=()=>request<Topic[]>('').then(setItems)
 useEffect(()=>{if(!role)return;void load().catch(e=>setError(e.message));const timer=setInterval(()=>void load().catch(e=>setError(e.message)),15000);return()=>clearInterval(timer)},[role])
 async function run(work:()=>Promise<void>){setBusy(true);setError('');try{await work();await load()}catch(e){setError(e instanceof Error?e.message:'Please try again')}finally{setBusy(false)}}
 if(!role)return null
 return <section className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
  <h2 className="font-semibold">{role==='parent'?'Learning topic requests':'Ask Dad about a learning topic'}</h2>
  <p className="text-sm text-[var(--muted-foreground)]">{role==='parent'?'Approve, change, or decline an idea. Approval does not generate or assign a course. Use an approved topic when preparing a reviewed course.':'What would you like to learn? Use a short subject, without names or personal details. Your parent reviews it before preparing a course.'}</p>
  {error&&<p role="alert">{error}</p>}
  {role==='learner'&&<form className="space-y-2" onSubmit={e=>{e.preventDefault();void run(async()=>{await request('',{request_id:randomUuid().replaceAll('-',''),topic:text});setText('')})}}>
   <label className="block">Topic<input className={fieldClass} value={text} minLength={3} maxLength={160} required onChange={e=>setText(e.target.value)} placeholder="For example: Python games or ancient Egypt"/></label>
   <button className={primaryClass} disabled={busy}>Ask Dad</button>
  </form>}
  {items.map(item=><article key={item.id} className="space-y-2 rounded-lg border border-[var(--border)] p-3">
   <p>{item.topic}</p><p className="text-sm" role="status">{item.status==='pending'?'Waiting for a parent':item.status==='approved'?'Approved topic: '+item.approved_topic:'Parent declined this topic. You can ask about another subject.'}</p>
   {role==='parent'&&item.status==='pending'&&<>
    <label className="block">Topic to approve<input className={fieldClass} maxLength={160} value={edits[item.id]??item.topic} onChange={e=>setEdits(prev=>({...prev,[item.id]:e.target.value}))}/></label>
    <button className={primaryClass} disabled={busy} onClick={()=>void run(async()=>{await request('/'+item.id+'/decision',{decision:'approve',expected_topic:item.topic,replacement:edits[item.id]??item.topic})})}>Approve topic</button>{' '}
    <button className={buttonClass} disabled={busy} onClick={()=>void run(async()=>{await request('/'+item.id+'/decision',{decision:'deny',expected_topic:item.topic})})}>Decline topic</button>
   </>}
  </article>)}
 </section>
}
