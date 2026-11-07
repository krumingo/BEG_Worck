import { HardHat } from "lucide-react";

// AUTH-01 — the frame of the public password screens: the same centered card,
// logo and background as the login page, so forgot/reset need no shell of
// their own. Full width with a 16px gutter on a phone, 400px on a desktop.
export default function AuthScreen({ title, subtitle, children, testId }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4 py-8" data-testid={testId}>
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: "radial-gradient(circle at 1px 1px, hsl(var(--foreground)) 1px, transparent 0)",
          backgroundSize: "40px 40px",
        }}
      />
      <div className="relative w-full max-w-[400px] animate-in">
        <div className="flex flex-col items-center mb-6 sm:mb-8 text-center">
          <div className="w-14 h-14 rounded-2xl bg-primary flex items-center justify-center mb-4 shadow-lg shadow-primary/20">
            <HardHat className="w-7 h-7 text-primary-foreground" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground mt-1 max-w-[320px]">{subtitle}</p>}
        </div>
        <div className="rounded-xl border border-border bg-card p-5 sm:p-6">{children}</div>
      </div>
    </div>
  );
}
