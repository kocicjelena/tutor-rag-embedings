import type { ProvidersPayload } from "@/lib/types";

/**
 * Who answers, and with which model.
 *
 * This slice exists because the same fact was being fetched and held in three places —
 * `app/page.tsx`, `components/tutor/TutorPage.tsx` and `app/status/page.tsx` — each with its
 * own copy of the "prefer the backend default, fall back to whatever is usable" rule. Three
 * copies of a rule is three chances for them to disagree, and the user's choice on one page
 * did not survive a move to the other.
 *
 * One slice, one fetch, one rule, and the choice follows the reader across the app.
 */
export interface ProvidersType {
  /** The catalogue as the backend reports it. Null until it has been asked. */
  data: ProvidersPayload | null;
  /** The provider the user is answering with. */
  provider: string;
  /** The model within that provider. Empty means "the provider's default". */
  model: string;
  loading: boolean;
  error: string | null;
  /**
   * True once a fetch has completed, successfully or not. Distinguishes "not asked yet" from
   * "asked, and there is nothing" — without it the picker cannot tell loading from empty.
   */
  loaded: boolean;
}

export const initialProviders: ProvidersType = {
  data: null,
  provider: "ollama",
  model: "",
  loading: false,
  error: null,
  loaded: false,
};
