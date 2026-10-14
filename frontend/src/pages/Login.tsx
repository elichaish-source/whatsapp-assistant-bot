import { useState, type FormEvent } from "react";
import { api } from "../api";

export default function Login({ onLogin }: { onLogin: (phone: string) => void }) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const requestCode = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api("/auth/request-code", { method: "POST", body: { phone } });
      setStep("code");
    });
  };

  const verify = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const me = await api<{ phone: string }>("/auth/verify", { method: "POST", body: { phone, code } });
      onLogin(me.phone);
    });
  };

  return (
    <div className="center">
      <div className="card login-card">
        <h1>כניסה לדשבורד</h1>
        {step === "phone" ? (
          <form onSubmit={requestCode}>
            <label>
              מספר וואטסאפ
              <input
                type="tel"
                dir="ltr"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="050-1234567"
                autoFocus
                required
              />
            </label>
            <button className="primary" disabled={busy}>
              שלח לי קוד
            </button>
          </form>
        ) : (
          <form onSubmit={verify}>
            <p className="muted">אם המספר רשום, נשלח אליו קוד ב"הודעה לעצמי" בוואטסאפ.</p>
            <label>
              קוד
              <input
                inputMode="numeric"
                dir="ltr"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                maxLength={6}
                autoFocus
                required
              />
            </label>
            <button className="primary" disabled={busy}>
              כניסה
            </button>
            <button type="button" className="link-btn" onClick={() => setStep("phone")}>
              חזרה
            </button>
          </form>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
