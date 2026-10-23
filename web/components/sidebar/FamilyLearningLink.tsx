"use client";

import Link from "next/link";
import { GraduationCap } from "lucide-react";
import { useEffect, useState, type MouseEvent } from "react";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { apiFetch } from "@/shared/api/client";

export function FamilyLearningLink({ collapsed = false, onNavigate }: {
  collapsed?: boolean;
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const { authenticated, isAdmin } = useAuthStatus();
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    if (!authenticated || !isAdmin) return;
    let active = true;
    void apiFetch("/api/family-learning", { skipAuthRedirect: true })
      .then(response => { if (active) setAvailable(response.ok); })
      .catch(() => { if (active) setAvailable(false); });
    return () => { active = false; };
  }, [authenticated, isAdmin]);
  if (!authenticated || !isAdmin || !available) return null;
  return <div className={collapsed ? "flex shrink-0 justify-center pb-1" : "shrink-0 px-2 pb-1"}>
    <Link href="/family-learning" prefetch={false} aria-label="Family Learning"
      title={collapsed ? "Family Learning" : undefined} onClick={onNavigate}
      className={"flex min-h-8 items-center rounded-md text-[13px] text-foreground/85 transition-colors hover:bg-background/60 hover:text-[var(--foreground)] " + (collapsed ? "justify-center p-2" : "gap-2 px-2.5 py-1.5")}>
      <GraduationCap size={15} strokeWidth={1.6} aria-hidden="true" />
      {!collapsed && <span>Family Learning</span>}
    </Link>
  </div>;
}
