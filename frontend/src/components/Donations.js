import { useEffect, useState } from "react";
import { CheckCircle2, HandCoins, Loader2, X, XCircle } from "lucide-react";
import api from "../api";

const PACKAGES = [
  { id: "don_5", amount: 5 },
  { id: "don_10", amount: 10 },
  { id: "don_25", amount: 25 },
  { id: "don_50", amount: 50 },
  { id: "don_100", amount: 100 },
];

export function DonateModal({ t, target, onClose }) {
  const [busy, setBusy] = useState(false);

  const donate = async (pkg) => {
    setBusy(true);
    try {
      const { data } = await api.post("/donations/checkout", {
        package_id: pkg.id,
        origin_url: window.location.origin,
        project_id: target?.id || null,
        project_title: target?.title || null,
      });
      window.location.href = data.checkout_url;
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/70 backdrop-blur-sm" data-testid="donate-modal">
      <div className="w-[380px] bg-surface border border-line rounded-sm p-5">
        <div className="flex items-center justify-between mb-1">
          <h3 className="font-heading font-bold text-base text-white flex items-center gap-2">
            <HandCoins size={16} className="text-sonar" /> {t("donateTitle")}
          </h3>
          <button data-testid="donate-close-btn" onClick={onClose} className="text-slate-500 hover:text-slate-200"><X size={15} /></button>
        </div>
        {target?.title && (
          <p className="text-xs text-slate-400 mb-3 truncate">{target.title}</p>
        )}
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">{t("chooseAmount")}</p>
        <div className="grid grid-cols-5 gap-2 mb-4">
          {PACKAGES.map((p) => (
            <button key={p.id} data-testid={`donate-amount-${p.amount}`} disabled={busy}
              onClick={() => donate(p)}
              className="py-2.5 font-heading font-bold text-sm border border-sonar/50 text-sonar rounded-sm hover:bg-sonar/15 disabled:opacity-40">
              {p.amount}€
            </button>
          ))}
        </div>
        <p className="text-[10px] text-slate-500 leading-relaxed">
          {busy ? <span className="flex items-center gap-1 text-sonar"><Loader2 size={11} className="animate-spin" /> {t("redirectingStripe")}</span> : t("stripeTestNote")}
        </p>
      </div>
    </div>
  );
}

export function PaymentReturn({ t, onDone }) {
  const [state, setState] = useState("checking");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id");
    const cancelled = window.location.pathname.startsWith("/payment/cancel");
    if (cancelled || !sessionId) {
      setState(cancelled ? "cancelled" : "error");
      return;
    }
    let attempts = 0;
    const poll = async () => {
      if (attempts++ > 10) { setState("timeout"); return; }
      try {
        const { data } = await api.get(`/payments/status/${sessionId}`);
        if (data.payment_status === "paid") { setState("paid"); return; }
        if (["failed", "expired"].includes(data.status)) { setState("error"); return; }
      } catch (e) { /* retry */ }
      setTimeout(poll, 2000);
    };
    poll();
  }, []);

  const close = () => {
    window.history.replaceState({}, "", "/");
    onDone();
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/70 backdrop-blur-sm" data-testid="payment-return-modal">
      <div className="w-[380px] bg-surface border border-line rounded-sm p-6 text-center">
        {state === "checking" && (
          <>
            <Loader2 size={32} className="animate-spin text-sonar mx-auto mb-3" />
            <p className="text-sm text-slate-300">{t("checkingPayment")}</p>
          </>
        )}
        {state === "paid" && (
          <>
            <CheckCircle2 size={36} className="text-bio mx-auto mb-3" />
            <p className="font-heading font-bold text-white mb-1" data-testid="payment-success-msg">{t("paymentSuccess")}</p>
            <p className="text-xs text-slate-400">{t("paymentThanks")}</p>
          </>
        )}
        {(state === "cancelled" || state === "error" || state === "timeout") && (
          <>
            <XCircle size={36} className="text-alert mx-auto mb-3" />
            <p className="font-heading font-bold text-white" data-testid="payment-fail-msg">
              {state === "cancelled" ? t("paymentCancelled") : t("paymentError")}
            </p>
          </>
        )}
        {state !== "checking" && (
          <button data-testid="payment-return-close" onClick={close}
            className="mt-4 px-4 py-2 text-xs font-semibold border border-sonar/50 text-sonar rounded-sm hover:bg-sonar/10">
            {t("backToMap")}
          </button>
        )}
      </div>
    </div>
  );
}
