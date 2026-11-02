import type { CurrentUser } from "@/lib/auth";

/** A sentence in both languages; the tour shows the one the user reads. */
export interface Words {
  vi: string;
  en: string;
}

/** One stop of a guide: what to look at and what it does. */
export interface TourStep {
  title: Words;
  body: Words;
  /** CSS selector of the element to highlight; none centres the card. */
  target?: string;
  /** Text the target must contain, for elements no selector tells apart. */
  text?: string;
  /** Selector of the ancestor to highlight instead of the matched element. */
  closest?: string;
  /** Page to open before the step shows. */
  href?: string;
  /** The page the target lives on, as a regex over the pathname; elsewhere the step shows `wait`. */
  path?: string;
  /** What to do to reach `path`, shown until the user gets there. */
  wait?: Words;
  side?: "top" | "right" | "bottom" | "left";
  /** Who sees this step; the rest skip it. */
  when?: (user: CurrentUser) => boolean;
}

/** A step-by-step guide to one feature, end to end. */
export interface Tour {
  id: string;
  title: Words;
  summary: Words;
  /** Who the guide is for; the rest never see it. */
  audience: (user: CurrentUser) => boolean;
  steps: TourStep[];
}
