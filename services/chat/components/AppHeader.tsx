"use client";

// The bar above every chat page: the app, Ask, the assistant and My tickets, the bell and the account.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, Bot, Building2, LogOut, MessageSquare, Ticket } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { AGENT_USE, DEPARTMENT_READ } from "@/lib/session";
import NotificationBell from "./NotificationBell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function AppHeader() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const onTickets = path.startsWith("/tickets");
  const onGuides = path.startsWith("/guides");
  const onDepartment = path.startsWith("/department");
  const onProfile = path.startsWith("/profile");
  const onAssistant = path.startsWith("/assistant");
  const tabs = [
    {
      href: "/",
      label: "Ask",
      icon: MessageSquare,
      active: !onTickets && !onGuides && !onDepartment && !onProfile && !onAssistant,
    },
    ...(user?.permissions?.includes(AGENT_USE)
      ? [{ href: "/assistant", label: "Assistant", icon: Bot, active: onAssistant }]
      : []),
    { href: "/tickets", label: "My tickets", icon: Ticket, active: onTickets },
    ...(user?.permissions?.includes(DEPARTMENT_READ)
      ? [{ href: "/department", label: "Department", icon: Building2, active: onDepartment }]
      : []),
  ];
  return (
    <header className="border-b border-border bg-card">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:shadow-float"
      >
        Skip to content
      </a>
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-2 px-3 sm:gap-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5 rounded-md">
          <span aria-hidden className="flex size-7 items-center justify-center rounded-md bg-primary font-display text-sm font-semibold text-primary-foreground">
            S
          </span>
          <span className="hidden flex-col leading-tight min-[420px]:flex">
            <span className="text-sm font-semibold">IT Help</span>
            <span className="hidden text-2xs text-muted-foreground sm:block">Answers from approved help pages</span>
          </span>
        </Link>
        <nav aria-label="Main" className="ml-auto flex items-center gap-1 sm:ml-6 sm:mr-auto">
          {tabs.map(({ href, label, icon: Icon, active }) => (
            <Link
              key={href}
              href={href}
              data-slot="nav-item"
              aria-current={active ? "page" : undefined}
              className={cn(
                "inline-flex h-9 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors",
                active ? "bg-primary-soft text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-1">
          <Link
            href="/guides"
            data-tour="guides-link"
            data-slot="nav-item"
            aria-current={onGuides ? "page" : undefined}
            aria-label="Guides"
            className={cn(
              "inline-flex h-9 items-center gap-1.5 rounded-md px-2 text-sm transition-colors",
              onGuides ? "text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <BookOpen className="size-4" aria-hidden />
            <span className="hidden md:inline">Guides</span>
          </Link>
          <NotificationBell />
          {user && (
            <Link
              href="/profile"
              aria-current={onProfile ? "page" : undefined}
              className="hidden max-w-32 truncate rounded-md px-1 text-sm text-muted-foreground hover:text-foreground lg:inline"
            >
              {user.username}
            </Link>
          )}
          <Button variant="ghost" size="sm" onClick={() => void logout()} className="text-muted-foreground" aria-label="Sign out">
            <LogOut aria-hidden />
            <span className="hidden md:inline">Sign out</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
