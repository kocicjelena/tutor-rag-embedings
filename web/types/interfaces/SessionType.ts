/**
 * Is this browser signed in?
 *
 * One field, and it still earns a slice: two pages asked the server separately, which is two
 * round trips and two chances to disagree about whether there is a user.
 */
export interface SessionType {
  /**
   * Null while unknown. The app cannot tell "signed out" from "not asked yet" without it,
   * and showing the sign-in form during that gap makes a signed-in user think they were
   * logged out.
   */
  signedIn: boolean | null;
}

export const initialSession: SessionType = {
  signedIn: null,
};
