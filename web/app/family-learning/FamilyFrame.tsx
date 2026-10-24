'use client'

import type {ReactNode} from 'react'
import AppShell from '@/components/layout/AppShell'
import {FeaturePage} from '@/components/layout/FeaturePage'
import UtilitySidebar from '@/components/sidebar/UtilitySidebar'
import {CapabilityAccessProvider} from '@/components/access/CapabilityAccessContext'
import styles from './family-learning.module.css'

export default function FamilyFrame({role,children}:{role:string;children:ReactNode}){
  const content=<FeaturePage><div className={styles.content}>{children}</div></FeaturePage>
  // Learners share the visual system, never the parent's general-purpose navigation.
  if(role!=='parent')return <div className="h-dvh min-h-0 bg-[var(--background)]">{content}</div>
  return <CapabilityAccessProvider><AppShell sidebar={<UtilitySidebar/>}>{content}</AppShell></CapabilityAccessProvider>
}
