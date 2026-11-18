"use client";

// The frame around every signed-in page: a sidebar with new chat, recent conversations, the other
// areas and the account; on a narrow screen it opens as a drawer from a slim top bar.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BookOpen, Building2, LogOut, Menu, Plus, Ticket, X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { AGENT_USE, DEPARTMENT_READ } from "@/lib/session";
import { useAssistant } from "./AssistantProvider";
import ConversationHistory from "./ConversationHistory";
import NotificationBell from "./NotificationBell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const BARE = ["/login", "/auth"];

function SidebarBody() {
  const { user, logout } = useAuth();
  const assistant = useAssistant();
  const path = usePathname();
  const router = useRouter();
  const canChat = !!user?.permissions?.includes(AGENT_USE);
  const currentId = assistant.rows.find((r) => r.kind === "server")?.turn.conversation_id ?? null;
  const links = [
    { href: "/tickets", label: "My tickets", icon: Ticket },
    ...(user?.permissions?.includes(DEPARTMENT_READ) ? [{ href: "/department", label: "Department", icon: Building2 }] : []),
    { href: "/guides", label: "Guides", icon: BookOpen, tour: "guides-link" },
  ];
  const onProfile = path.startsWith("/profile");

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-3">
      <Link href="/" className="flex shrink-0 items-center gap-2.5 rounded-md px-1">
        <span aria-hidden className="flex size-7 items-center justify-center rounded-md bg-primary font-display text-sm font-semibold text-primary-foreground">
          S
        </span>
        <span className="flex flex-col leading-tight">
          <span className="text-sm font-semibold">IT Help</span>
          <span className="text-2xs text-muted-foreground">Answers from approved help pages</span>
        </span>
      </Link>
      {canChat && (
        <Button
          variant="outline"
          onClick={() => {
            void assistant.startNew();
            router.push("/");
          }}
          disabled={assistant.rows.some((r) => r.kind === "sending")}
          className="justify-start"
        >
          <Plus aria-hidden /> New chat
        </Button>
      )}
      <nav aria-label="Main" className="flex flex-col gap-0.5">
        {links.map(({ href, label, icon: Icon, tour }) => {
          const active = path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              data-slot="nav-item"
              data-tour={tour}
              aria-current={active ? "page" : undefined}
              className={cn(
                "inline-flex h-9 items-center gap-2 rounded-md px-2 text-sm font-medium transition-colors",
                active ? "bg-primary-soft text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>
      {canChat ? (
        <ConversationHistory
          history={assistant.history}
          error={assistant.historyError}
          currentId={path === "/" ? currentId : null}
          onOpen={(id) => {
            void assistant.open(id);
            router.push("/");
          }}
        />
      ) : (
        <div className="flex-1" />
      )}
      <div className="mt-auto flex shrink-0 items-center gap-1 border-t border-border pt-3">
        {user && (
          <Link
            href="/profile"
            aria-current={onProfile ? "page" : undefined}
            className="min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            {user.username}
          </Link>
        )}
        <NotificationBell />
        <Button variant="ghost" size="sm" onClick={() => void logout()} className="text-muted-foreground" aria-label="Sign out">
          <LogOut aria-hidden />
        </Button>
      </div>
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const path = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);

  if (!user || BARE.some((p) => path.startsWith(p))) return <>{children}</>;

  return (
    <div className="flex h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:shadow-float"
      >
        Skip to content
      </a>
      <aside className="hidden w-64 shrink-0 border-r border-border bg-card md:block">
        <SidebarBody />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button aria-label="Close menu" onClick={() => setOpen(false)} className="absolute inset-0 bg-foreground/40" />
          <aside className="relative h-full w-72 max-w-[85vw] border-r border-border bg-card shadow-float">
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)} aria-label="Close menu" className="absolute right-2 top-2">
              <X aria-hidden />
            </Button>
            <SidebarBody />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-card px-3 md:hidden">
          <Button variant="ghost" size="sm" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu aria-hidden />
          </Button>
          <span className="text-sm font-semibold">IT Help</span>
        </div>
        {children}
      </div>
    </div>
  );
}
