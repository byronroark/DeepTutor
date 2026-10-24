'use client'

import {useRef} from 'react'
import {PrismLight as Highlighter} from 'react-syntax-highlighter'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import styles from './python-editor.module.css'

Highlighter.registerLanguage('python', python)

/** The real textarea remains the accessible editing surface; highlighting is decorative. */
export default function PythonEditor({value,onChange,disabled=false}:{value:string;onChange:(value:string)=>void;disabled?:boolean}) {
  const paint=useRef<HTMLDivElement>(null)
  return <div className={styles.editor}>
    <div ref={paint} className={styles.paint} aria-hidden="true">
      <Highlighter language="python" useInlineStyles={false}>{value+'\n'}</Highlighter>
    </div>
    <textarea aria-label="Your Python program" className={styles.input} value={value}
      onChange={event=>onChange(event.target.value)} disabled={disabled} rows={8}
      maxLength={16384} spellCheck={false} autoCapitalize="off" autoCorrect="off" wrap="off"
      onScroll={event=>{if(paint.current){paint.current.scrollTop=event.currentTarget.scrollTop;paint.current.scrollLeft=event.currentTarget.scrollLeft}}}/>
  </div>
}
