"use client";

// What I can do and why (F14, FR-F14-011): every permission the signed-in person holds, where, and the grant behind it.

import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Page, PageHeader } from "@/components/ui/page-header";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { shortUrn } from "@/lib/permissions";
import type { PersonAccessOut } from "@/lib/types/generated";

export default function MyAccessPage() {
  const user = useRequireAuth();
  const [access, setAccess] = useState<PersonAccessOut | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!user) return;
    api
      .get<PersonAccessOut>("/api/access/me")
      .then(setAccess)
      .catch(() => setError(true));
  }, [user]);

  const rows = useMemo(
    () => (access?.permissions ?? []).filter((p) => !filter.trim() || p.urn.includes(filter.trim().toLowerCase())),
    [access, filter],
  );

  if (!user) return null;
  return (
    <Page width="record" className="flex flex-col gap-4">
      <PageHeader
        eyebrow="Workspace / Me"
        title="My access"
        description={
          <>
            Your base role is <span className="font-medium capitalize text-foreground">{user.role}</span>
            {user.department ? <>, in {user.department.name}</> : null}. Ask an access admin if something is missing.
          </>
        }
        actions={<Input className="w-60" placeholder="Filter permissions" value={filter} onChange={(e) => setFilter(e.target.value)} />}
      />
      {error && <ErrorState title="Couldn't load your access." />}
      {!access && !error && <LoadingState rows={6} />}
      {access && (
        <Card className="overflow-x-auto">
          <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow>
                <TableHead>Permission</TableHead>
                <TableHead>Where</TableHead>
                <TableHead>From</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.urn}>
                  <TableCell className="font-mono text-xs">{shortUrn(p.urn)}</TableCell>
                  <TableCell className="text-sm">
                    {p.scope.everywhere ? "Everywhere" : [...p.scope.teams.map((t) => `team ${t}`), ...p.scope.departments.map((d) => `dept ${d}`)].join(", ")}
                  </TableCell>
                  <TableCell className="text-sm">
                    {p.sources.map((s, i) => (
                      <span key={i} className="block">
                        {s.role_name}
                        <span className="text-muted-foreground">
                          {" "}
                          at {s.scope}
                          {s.ends_at ? ` · until ${formatDate(s.ends_at)}` : ""}
                        </span>
                      </span>
                    ))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </Page>
  );
}
