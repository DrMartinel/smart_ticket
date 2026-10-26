"use client";

// One ticket (F3 · Ticket thread 10-580, Rating 10-623): where it stands, the public thread, a
// reply box while it is open, and the rating and reopen once it is resolved.

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import AppHeader from "@/components/AppHeader";
import Rating, { day } from "@/components/Rating";
import ReopenBox from "@/components/ReopenBox";
import { ApiError, notificationsApi, requesterApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { RequesterTicketOut, ThreadCommentOut } from "@/lib/types/generated";

// Until the first poll says otherwise (NOTIFICATION_POLL_SEC, FR-F3-014).
const FIRST_POLL_SEC = 15;

export default function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const { user, loading } = useAuth();
  const router = useRouter();
  const [ticket, setTicket] = useState<RequesterTicketOut | null>(null);
  const [missing, setMissing] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const pollSec = useRef(FIRST_POLL_SEC);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  const load = useCallback(async () => {
    try {
      setTicket(await requesterApi.ticket(id));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setMissing(true);
    }
  }, [id]);

  // Loads the thread now, then polls it while it is on screen (FR-F3-014).
  useEffect(() => {
    if (!user) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let alive = true;
    const schedule = () => {
      timer = setTimeout(async () => {
        if (!document.hidden) await load();
        if (alive) schedule();
      }, pollSec.current * 1000);
    };
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    notificationsApi
      .unread()
      .then((inbox) => (pollSec.current = inbox.poll_sec))
      .catch(() => undefined);
    void load().then(() => alive && schedule());
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [user, load]);

  if (!user) return null;

  const send = async () => {
    setSending(true);
    setNotice(null);
    try {
      const comment = await requesterApi.reply(id, text);
      setText("");
      if (comment.credential_masked)
        setNotice("Your reply was saved with personal details hidden. Vui lòng không gửi mật khẩu.");
      else if (comment.state === "checking") setNotice("Đã nhận, đang kiểm tra · Received; it's being checked.");
      await load();
    } catch (err) {
      setNotice(
        err instanceof ApiError && err.code === "ticket_closed"
          ? "Yêu cầu đã được giải quyết · This ticket is resolved: reopen it below."
          : "Không gửi được · Couldn't send your reply.",
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
        {missing && <p className="text-sm text-[var(--text-muted)]">Không tìm thấy yêu cầu · No such ticket.</p>}
        {ticket && (
          <>
            <header className="flex flex-col gap-1">
              <p className="flex items-start justify-between gap-3">
                <span className="font-mono text-xs text-[var(--text-muted)]">{ticket.public_id}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    ticket.sla_paused
                      ? "bg-[var(--warn-soft)] text-[var(--warn)]"
                      : ticket.resolved_at
                        ? "bg-[var(--ok-soft)] text-[var(--ok)]"
                        : "bg-[var(--accent-soft)] text-[var(--accent)]"
                  }`}
                >
                  {ticket.status_label}
                </span>
              </p>
              <h1 className="text-lg font-semibold">{ticket.subject_masked}</h1>
              <p className="text-xs text-[var(--text-muted)]">
                {[
                  ticket.team ? `${ticket.team} team` : null,
                  `opened ${day(ticket.created_at)}`,
                  ticket.sla_paused ? "SLA paused while we wait for you" : null,
                  ticket.resolution_due_at ? `due ${day(ticket.resolution_due_at)}` : null,
                  ticket.reopened_from ? `related to ${ticket.reopened_from}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </header>

            <ol className="flex flex-col gap-3">
              {ticket.thread.map((c) => (
                <li key={c.id}>
                  <Comment comment={c} />
                </li>
              ))}
            </ol>

            {notice && <p className="rounded-[5px] bg-[var(--warn-soft)] px-3 py-2 text-xs text-[var(--warn)]">{notice}</p>}

            {ticket.can_reply && (
              <form
                className="panel flex flex-col gap-2 px-4 py-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void send();
                }}
              >
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={10_000}
                  placeholder="Viết trả lời… · Write a reply…"
                  aria-label="Reply"
                  className="min-h-[64px] resize-none bg-transparent text-[15px] outline-none"
                />
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-[var(--text-muted)]">
                    {ticket.sla_paused ? "Replying moves the ticket back to the team." : "Personal details are hidden before saving."}
                  </span>
                  <button type="submit" disabled={sending || !text.trim()} className="btn btn-primary">
                    {sending ? "…" : "Gửi · Send"}
                  </button>
                </div>
              </form>
            )}

            {ticket.resolved_at && (
              <>
                {ticket.can_rate && (
                  <section className="panel px-4 py-4">
                    <Rating publicId={ticket.public_id} current={ticket.rating_detail} until={ticket.can_reopen_until} />
                  </section>
                )}
                <section className="panel flex flex-col gap-2 px-4 py-4">
                  <h2 className="font-medium">Chưa giải quyết được? · Still not fixed?</h2>
                  <ReopenBox publicId={ticket.public_id} until={ticket.can_reopen_until} onDone={() => void load()} />
                </section>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function Comment({ comment }: { comment: ThreadCommentOut }) {
  const who = comment.mine ? "You" : comment.author_kind === "system" ? "IT Help" : comment.author;
  const body =
    comment.state === "checking"
      ? "Đã nhận, đang kiểm tra · Received; it's being checked."
      : comment.state === "discarded"
        ? "Không gửi được, vui lòng gửi lại · This reply couldn't be delivered; please send it again."
        : comment.body_masked;
  return (
    <article
      className={`rounded-[6px] px-4 py-3 ${comment.mine ? "bg-[var(--accent-soft)]" : "panel"}`}
    >
      <p className="text-xs text-[var(--text-muted)]">
        {who} · {new Date(comment.created_at).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
      </p>
      <p className={`mt-1 whitespace-pre-wrap break-words text-[15px] ${comment.state === "shown" ? "" : "italic text-[var(--text-muted)]"}`}>
        {body}
      </p>
    </article>
  );
}
