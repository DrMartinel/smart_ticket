"use client";

// Draws one step of a guide: a dimmed page with the target cut out, and a card beside it.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { TourStep, Words } from "./types";

const PAD = 6;
const GAP = 12;
const MARGIN = 16;
const CARD_WIDTH = 360;
const FIND_FOR_MS = 4000;
const POLL_MS = 150;

const CHROME = {
  back: { vi: "Quay lại", en: "Back" },
  next: { vi: "Tiếp", en: "Next" },
  finish: { vi: "Xong", en: "Finish" },
  skip: { vi: "Bỏ qua hướng dẫn", en: "Skip guide" },
  missing: {
    vi: "Mục này không hiện trên trang lúc này (có thể trang chưa có dữ liệu, hoặc vai trò của bạn không thấy nó). Bấm Tiếp để đi tiếp.",
    en: "This isn't on the page right now (the page may have no data yet, or your role doesn't show it). Press Next to go on.",
  },
};

interface Props {
  step: TourStep;
  index: number;
  count: number;
  language: "vi" | "en";
  pathname: string;
  onBack: () => void;
  onNext: () => void;
  onClose: () => void;
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

function boxOf(el: Element): Box {
  const r = el.getBoundingClientRect();
  return { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 };
}

/** The element a step points at: the first visible match, outside the guide itself. */
function findTarget(step: TourStep): Element | null {
  if (!step.target) return null;
  for (const el of document.querySelectorAll(step.target)) {
    if (el.closest("[data-tour-overlay]") || el.getClientRects().length === 0) continue;
    if (step.text && !el.textContent?.includes(step.text)) continue;
    return step.closest ? el.closest(step.closest) ?? el : el;
  }
  return null;
}

function clamp(value: number, low: number, high: number) {
  return Math.max(low, Math.min(value, Math.max(low, high)));
}

/** Where the card goes beside `box`, kept inside the window. */
function placeCard(box: Box, card: { width: number; height: number }, side: TourStep["side"]) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const fits = {
    right: box.left + box.width + GAP + card.width <= vw - MARGIN,
    left: box.left - GAP - card.width >= MARGIN,
    bottom: box.top + box.height + GAP + card.height <= vh - MARGIN,
    top: box.top - GAP - card.height >= MARGIN,
  };
  const order: NonNullable<TourStep["side"]>[] = [side ?? "bottom", "bottom", "right", "top", "left"];
  const chosen = order.find((s) => fits[s]);
  let top: number;
  let left: number;
  switch (chosen) {
    case "right":
      left = box.left + box.width + GAP;
      top = box.top;
      break;
    case "left":
      left = box.left - GAP - card.width;
      top = box.top;
      break;
    case "top":
      top = box.top - GAP - card.height;
      left = box.left;
      break;
    case "bottom":
      top = box.top + box.height + GAP;
      left = box.left;
      break;
    default:
      // Nothing beside it fits (a tall or wide target): lay the card over its lower right.
      top = vh - card.height - MARGIN;
      left = vw - card.width - MARGIN;
  }
  return {
    top: clamp(top, MARGIN, vh - card.height - MARGIN),
    left: clamp(left, MARGIN, vw - card.width - MARGIN),
  };
}

export default function TourOverlay({ step, index, count, language, pathname, onBack, onNext, onClose }: Props) {
  const say = (w: Words) => w[language];
  const onPage = !step.path || new RegExp(step.path).test(pathname);
  const [element, setElement] = useState<Element | null>(null);
  const [gaveUp, setGaveUp] = useState(false);
  const [box, setBox] = useState<Box | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [cardPos, setCardPos] = useState<{ top: number; left: number } | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    setElement(null);
    setGaveUp(false);
    if (!step.target || !onPage) return;
    const started = Date.now();
    let scrolled = false;
    const find = () => {
      const found = findTarget(step);
      if (found) {
        setElement(found);
        if (!scrolled) {
          scrolled = true;
          const tall = found.getBoundingClientRect().height > window.innerHeight * 0.6;
          found.scrollIntoView({ block: tall ? "start" : "center", inline: "nearest" });
        }
        return true;
      }
      if (Date.now() - started > FIND_FOR_MS) {
        setGaveUp(true);
        return true;
      }
      return false;
    };
    if (find()) return;
    const timer = window.setInterval(() => find() && window.clearInterval(timer), POLL_MS);
    return () => window.clearInterval(timer);
  }, [step, onPage]);

  useEffect(() => {
    if (!element) {
      setBox(null);
      return;
    }
    const measure = () => {
      if (!element.isConnected) {
        const again = findTarget(step);
        if (again && again !== element) setElement(again);
        return;
      }
      setBox(boxOf(element));
    };
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    const timer = window.setInterval(measure, 300);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
      window.clearInterval(timer);
    };
  }, [element, step]);

  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const size = { width: card.offsetWidth, height: card.offsetHeight };
    setCardPos(box ? placeCard(box, size, step.side) : null);
  }, [box, step.side, onPage, gaveUp, mounted]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && e.target.closest("input, textarea, select, [contenteditable]");
      if (e.key === "Escape") onClose();
      else if (typing) return;
      else if (e.key === "ArrowRight") onNext();
      else if (e.key === "ArrowLeft" && index > 0) onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onNext, onBack, index]);

  if (!mounted) return null;

  const last = index + 1 >= count;
  const centred = !step.target;
  const searching = !!step.target && onPage && !element && !gaveUp;

  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-[60]" data-tour-overlay>
      {box ? (
        <div
          aria-hidden
          className="absolute rounded-lg ring-2 ring-primary transition-all duration-200"
          style={{ ...box, boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.6)" }}
        />
      ) : (
        centred && <div aria-hidden className="absolute inset-0 bg-black/60" />
      )}
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="false"
        aria-labelledby="tour-title"
        className={`pointer-events-auto absolute rounded-lg border bg-popover p-5 text-popover-foreground shadow-lg ${
          centred ? "top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" : box ? "" : "right-4 bottom-4"
        }`}
        style={{
          width: `min(${CARD_WIDTH}px, calc(100vw - ${MARGIN * 2}px))`,
          ...(box ? (cardPos ?? { visibility: "hidden" }) : {}),
          ...(searching ? { visibility: "hidden" } : {}),
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <p className="font-mono text-xs text-muted-foreground">
            {index + 1} / {count}
          </p>
          <button
            onClick={onClose}
            className="-mr-1 -mt-1 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label={say(CHROME.skip)}
          >
            <X className="size-4" />
          </button>
        </div>
        <h2 id="tour-title" className="mt-1 text-base font-semibold">
          {say(step.title)}
        </h2>
        <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">{say(step.body)}</p>
        {!onPage && step.wait && (
          <p className="mt-3 rounded-md bg-info-soft px-3 py-2 text-sm text-info">{say(step.wait)}</p>
        )}
        {onPage && gaveUp && (
          <p className="mt-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{say(CHROME.missing)}</p>
        )}
        <div className="mt-4 flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {say(CHROME.skip)}
          </Button>
          <div className="flex gap-2">
            {index > 0 && (
              <Button variant="outline" size="sm" onClick={onBack}>
                {say(CHROME.back)}
              </Button>
            )}
            <Button size="sm" onClick={onNext} autoFocus>
              {last ? say(CHROME.finish) : say(CHROME.next)}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
