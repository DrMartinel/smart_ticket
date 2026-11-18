"use client";

// Holds the assistant conversation above every page, so the sidebar and the chat page share it
// and it survives a visit to another page.

import { createContext, useContext } from "react";
import { useAuth } from "@/lib/auth";
import { useAgentConversation } from "@/lib/agent";
import { AGENT_USE } from "@/lib/session";

type Assistant = ReturnType<typeof useAgentConversation>;

const AssistantContext = createContext<Assistant | null>(null);

function Holder({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  const assistant = useAgentConversation(enabled);
  return <AssistantContext.Provider value={assistant}>{children}</AssistantContext.Provider>;
}

export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const enabled = !!user?.permissions?.includes(AGENT_USE);
  return (
    <Holder key={user?.username ?? "signed-out"} enabled={enabled}>
      {children}
    </Holder>
  );
}

export function useAssistant(): Assistant {
  const assistant = useContext(AssistantContext);
  if (!assistant) throw new Error("useAssistant needs an AssistantProvider");
  return assistant;
}
