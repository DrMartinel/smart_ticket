"use client";

// One security group (F17 FR-F17-013, BR-F17-08): its rules, and the assistant's drafts to add or
// remove one, applied here by a person.

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import ResourceChanges from "@/components/infra/ResourceChanges";
import { ResourceFrame, readError, useProjects } from "@/components/infra/shared";
import { Card } from "@/components/ui/card";
import { Facts, Panel } from "@/components/ui/panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { describeRule } from "@/lib/infra";
import { P, can } from "@/lib/permissions";
import type { SecurityGroupDetailOut } from "@/lib/types/generated";

export default function SecurityGroupPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const reads = can(user, P.infraRead);
  const projects = useProjects(reads);
  const [group, setGroup] = useState<SecurityGroupDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<SecurityGroupDetailOut>(`/api/infra/security-groups/${encodeURIComponent(id)}`)
      .then((g) => {
        setGroup(g);
        setError(null);
      })
      .catch((err) => setError(readError(err, "security group")));
  }, [id]);

  useEffect(() => {
    if (reads) load();
  }, [reads, load]);

  return (
    <ResourceFrame
      kind="Security group"
      title={group?.name || id}
      loaded={!!group}
      error={error}
      onRetry={load}
      meta={
        group && (
          <>
            <span>{projects[group.project_id] ?? group.project_id}</span>
            <span className="font-mono text-xs">{group.id}</span>
          </>
        )
      }
    >
      {group && (
        <>
          <ResourceChanges kind="security_group" id={group.id} name={group.name || group.id} rules={group.rules} onChanged={load} />
          <Panel title="State" id="state">
            <Facts termWidth="130px">
              <dt className="text-muted-foreground">Project</dt>
              <dd>{projects[group.project_id] ?? <span className="font-mono text-xs">{group.project_id || "—"}</span>}</dd>
              <dt className="text-muted-foreground">Rules</dt>
              <dd>{group.rules.length}</dd>
              {group.description && (
                <>
                  <dt className="text-muted-foreground">Description</dt>
                  <dd className="whitespace-pre-wrap">{group.description}</dd>
                </>
              )}
            </Facts>
          </Panel>
          <Card className="overflow-x-auto">
            <Table className="min-w-[640px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Rule</TableHead>
                  <TableHead>Ether type</TableHead>
                  <TableHead>Id</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {group.rules.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={3} className="text-muted-foreground">
                      This group has no rules.
                    </TableCell>
                  </TableRow>
                )}
                {group.rules.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>{describeRule(r)}</TableCell>
                    <TableCell>{r.ethertype}</TableCell>
                    <TableCell className="font-mono text-xs">{r.id}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </>
      )}
    </ResourceFrame>
  );
}
