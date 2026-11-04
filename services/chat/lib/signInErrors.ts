// What each sign-in refusal code means, in Vietnamese and English (F13, FR-F13-012).

export interface SignInErrorText {
  vi: string;
  en: string;
}

export const SIGN_IN_ERRORS: Record<string, SignInErrorText> = {
  no_access: {
    vi: "Tài khoản này không đăng nhập bằng tài khoản công ty",
    en: "This account can't use company sign-in. Use its own sign-in page.",
  },
  oidc_token_invalid: {
    vi: "Phiên đăng nhập đã hết hạn",
    en: "The sign-in expired or was refused. Try again.",
  },
  idp_unavailable: {
    vi: "Hệ thống đăng nhập công ty đang gián đoạn",
    en: "Company sign-in is down. IT is on it; try again in a few minutes.",
  },
  redirect_uri_not_allowed: {
    vi: "Địa chỉ đăng nhập của ứng dụng chưa được đăng ký",
    en: "This app's sign-in address isn't registered with core-api.",
  },
  state_mismatch: {
    vi: "Phiên đăng nhập không khớp với trình duyệt này",
    en: "The sign-in didn't start in this browser tab. Try again.",
  },
  keycloak_error: {
    vi: "Đăng nhập công ty bị huỷ hoặc thất bại",
    en: "Company sign-in was cancelled or failed. Try again.",
  },
};

export function signInError(code: string | null): SignInErrorText & { code: string } {
  const known = code && SIGN_IN_ERRORS[code] ? code : "oidc_token_invalid";
  return { code: known, ...SIGN_IN_ERRORS[known] };
}
