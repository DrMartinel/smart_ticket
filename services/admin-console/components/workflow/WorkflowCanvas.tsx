"use client";

// The workflow diagram: statuses as draggable nodes, transitions as edges between their connection points.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  ConnectionMode,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { POINTS, POINT_PLACEMENT, parseCoordinates, type Point, type Status, type Transition } from "@/lib/lifecycle";

type StatusNodeData = { status: Status; used: Set<Point>; editable: boolean; selected: boolean };
type StatusNode = Node<StatusNodeData, "status">;

const SIDE: Record<string, Position> = { top: Position.Top, right: Position.Right, bottom: Position.Bottom, left: Position.Left };
const GRID = 16;
const COLUMN = 240;
const ROW = 144;
const DOUBLE_CLICK_MS = 400;

function StatusNodeView({ data }: NodeProps<StatusNode>) {
  const { status, used, editable, selected } = data;
  const color = status.color || "#6b665c";
  return (
    <div
      className="group relative w-[184px] rounded-[6px] border bg-[var(--surface)] text-left shadow-sm"
      style={{ borderColor: selected ? "var(--text)" : `${color}66`, boxShadow: selected ? `0 0 0 1px var(--text)` : undefined }}
    >
      {POINTS.map((p) => {
        const { side, at } = POINT_PLACEMENT[p];
        const horizontal = side === "top" || side === "bottom";
        const visible = used.has(p);
        return (
          <Handle
            key={p}
            id={p}
            type="source"
            position={SIDE[side]}
            isConnectable={editable}
            style={{
              [horizontal ? "left" : "top"]: `${at}%`,
              background: visible ? color : "var(--surface)",
              borderColor: color,
            }}
            className={`!h-2.5 !w-2.5 !border ${visible ? "" : "opacity-0 group-hover:opacity-100"}`}
          />
        );
      })}
      <div className="h-1 rounded-t-[5px]" style={{ background: color }} />
      <div className="px-3 pb-2.5 pt-2">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px] font-semibold">{status.name}</span>
          {status.is_pipeline && (
            <span title="Triage status: only the pipeline moves tickets in" className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
              Triage
            </span>
          )}
        </div>
        <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-[var(--text-muted)]">
          <span className="truncate">{status.base.name}</span>
          {status.actions.length > 0 && <span title="Actions run on enter">⚡ {status.actions.length}</span>}
        </div>
      </div>
    </div>
  );
}

const nodeTypes = { status: StatusNodeView };

export default function WorkflowCanvas({
  statuses,
  transitions,
  editable,
  selected,
  onSelect,
  onMove,
  onConnect,
  onEditStatus,
  onEditTransition,
}: {
  statuses: Status[];
  transitions: Transition[];
  editable: boolean;
  selected: { kind: "status" | "transition"; id: string } | null;
  onSelect: (sel: { kind: "status" | "transition"; id: string } | null) => void;
  onMove: (status: Status, at: { x: number; y: number }) => void;
  onConnect: (c: { from: string; to: string; pointStart: Point; pointEnd: Point }) => void;
  onEditStatus: (status: Status) => void;
  onEditTransition: (transition: Transition) => void;
}) {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const q = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(q.matches);
    const on = (e: MediaQueryListEvent) => setDark(e.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);

  const builtNodes = useMemo<StatusNode[]>(() => {
    const ordered = [...statuses].sort((a, b) => a.order - b.order);
    const placed = ordered.map((s) => parseCoordinates(s.coordinates)).filter((p) => p !== null);
    const top = placed.length ? Math.max(...placed.map((p) => p.y)) + ROW : 0;
    const left = placed.length ? Math.min(...placed.map((p) => p.x)) : 0;
    let unplaced = 0;
    return ordered.map((status) => {
      const used = new Set<Point>();
      for (const t of transitions) {
        if (t.from_status_id === status.id) used.add(t.point_start);
        if (t.to_status_id === status.id) used.add(t.point_end);
      }
      const position = parseCoordinates(status.coordinates) ?? autoPlace(unplaced++, left, top);
      return {
        id: status.id,
        type: "status",
        position,
        draggable: editable,
        data: { status, used, editable, selected: selected?.kind === "status" && selected.id === status.id },
      };
    });
  }, [statuses, transitions, editable, selected]);

  const builtEdges = useMemo<Edge[]>(() => {
    const colorOf = Object.fromEntries(statuses.map((s) => [s.id, s.color || "#6b665c"]));
    return transitions.map((t) => {
      const isSelected = selected?.kind === "transition" && selected.id === t.id;
      const stroke = isSelected ? "var(--text)" : colorOf[t.from_status_id];
      const marker = { type: MarkerType.ArrowClosed, width: 14, height: 14, color: isSelected ? (dark ? "#ece9e2" : "#1f1d1a") : colorOf[t.from_status_id] };
      const extras = t.rules.length + t.actions.length;
      return {
        id: t.id,
        source: t.from_status_id,
        target: t.to_status_id,
        sourceHandle: t.point_start,
        targetHandle: t.point_end,
        type: "smoothstep",
        label: extras ? `${t.name} · ${extras}` : t.name,
        labelStyle: { fontSize: 11, fill: "var(--text)", fontWeight: isSelected ? 600 : 400 },
        labelBgStyle: { fill: "var(--surface)" },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 3,
        style: { stroke, strokeWidth: isSelected ? 2.5 : 1.75 },
        markerEnd: marker,
        markerStart: t.is_bidirectional ? marker : undefined,
      };
    });
  }, [statuses, transitions, selected, dark]);

  const [nodes, setNodes, onNodesChange] = useNodesState<StatusNode>(builtNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(builtEdges);
  useEffect(
    () =>
      setNodes((current) => {
        const previous = new Map(current.map((n) => [n.id, n]));
        return builtNodes.map((n) => {
          const before = previous.get(n.id);
          return before ? { ...before, position: n.position, draggable: n.draggable, data: n.data } : n;
        });
      }),
    [builtNodes, setNodes],
  );
  useEffect(() => setEdges(builtEdges), [builtEdges, setEdges]);

  const byId = useMemo(() => Object.fromEntries(statuses.map((s) => [s.id, s])), [statuses]);
  const transitionById = useMemo(() => Object.fromEntries(transitions.map((t) => [t.id, t])), [transitions]);

  const lastClick = useRef<{ id: string; at: number } | null>(null);
  const isSecondClick = (id: string) => {
    const now = Date.now();
    const second = lastClick.current?.id === id && now - lastClick.current.at < DOUBLE_CLICK_MS;
    lastClick.current = second ? null : { id, at: now };
    return second;
  };

  const handleConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target || c.source === c.target) return;
      onConnect({ from: c.source, to: c.target, pointStart: (c.sourceHandle ?? "3") as Point, pointEnd: (c.targetHandle ?? "7") as Point });
    },
    [onConnect],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeDragStop={(_, node) => byId[node.id] && onMove(byId[node.id], node.position)}
      onNodeClick={(_, node) => {
        onSelect({ kind: "status", id: node.id });
        if (isSecondClick(node.id) && byId[node.id]) onEditStatus(byId[node.id]);
      }}
      onEdgeClick={(_, edge) => {
        onSelect({ kind: "transition", id: edge.id });
        if (isSecondClick(edge.id) && transitionById[edge.id]) onEditTransition(transitionById[edge.id]);
      }}
      onPaneClick={() => onSelect(null)}
      onConnect={handleConnect}
      connectionMode={ConnectionMode.Loose}
      nodesConnectable={editable}
      edgesFocusable
      deleteKeyCode={null}
      zoomOnDoubleClick={false}
      snapToGrid
      snapGrid={[GRID, GRID]}
      fitView
      fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
      minZoom={0.3}
      colorMode={dark ? "dark" : "light"}
      proOptions={{ hideAttribution: true }}
      className="!bg-[var(--bg)]"
    >
      <Background gap={GRID} size={1} color="var(--border)" />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeColor={(n) => (n.data as StatusNodeData).status.color || "#6b665c"} className="!bg-[var(--surface)]" />
    </ReactFlow>
  );
}

function autoPlace(i: number, left: number, top: number) {
  const perRow = 4;
  return { x: left + (i % perRow) * COLUMN, y: top + Math.floor(i / perRow) * ROW };
}
