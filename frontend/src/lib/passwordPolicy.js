// AUTH-01 — the password rules the server enforces (validate_password_strength
// in backend/app/routes/auth.py), mirrored for live feedback only. The server
// stays the judge: this list never lets a password through on its own.
export const PASSWORD_SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:,.<>?";

export const PASSWORD_RULES = [
  { key: "length", labelKey: "auth.reqLength", test: (pw) => [...pw].length >= 10 },
  { key: "upper", labelKey: "auth.reqUpper", test: (pw) => [...pw].some((c) => c !== c.toLowerCase()) },
  { key: "lower", labelKey: "auth.reqLower", test: (pw) => [...pw].some((c) => c !== c.toUpperCase()) },
  { key: "digit", labelKey: "auth.reqDigit", test: (pw) => /\d/.test(pw) },
  { key: "special", labelKey: "auth.reqSpecial", test: (pw) => [...pw].some((c) => PASSWORD_SPECIAL_CHARS.includes(c)) },
];

export function passwordChecks(password) {
  const pw = password || "";
  return PASSWORD_RULES.map((rule) => ({ ...rule, ok: rule.test(pw) }));
}

export function passwordMeetsPolicy(password) {
  return passwordChecks(password).every((c) => c.ok);
}
