import { useState, useEffect } from "react";
import API from "@/lib/api";
import { CreditCard, Loader2, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";

export default function PlatformBillingPage() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    try {
      const res = await API.get("/billing/config");
      setConfig(res.data);
    } catch (err) {
      console.error("Failed to fetch billing config:", err);
      setError(err.response?.data?.detail || "Failed to load billing configuration");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-violet-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-6 text-red-400">
        <AlertTriangle className="w-6 h-6 mb-2" />
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="platform-billing-page">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <CreditCard className="w-6 h-6 text-violet-500" />
          Billing Configuration
        </h1>
        <p className="text-slate-400 mt-1">Stripe payment gateway settings</p>
      </div>

      {/* Stripe Status */}
      <div className={`rounded-xl border p-6 ${
        config.stripe_mock_mode 
          ? 'bg-amber-500/10 border-amber-500/20' 
          : 'bg-emerald-500/10 border-emerald-500/20'
      }`}>
        <div className="flex items-center gap-3">
          {config.stripe_mock_mode ? (
            <AlertTriangle className="w-6 h-6 text-amber-400" />
          ) : (
            <CheckCircle2 className="w-6 h-6 text-emerald-400" />
          )}
          <div>
            <h3 className={`font-semibold ${config.stripe_mock_mode ? 'text-amber-400' : 'text-emerald-400'}`}>
              {config.stripe_mock_mode ? 'Mock Mode Active' : 'Stripe Connected'}
            </h3>
            <p className="text-sm text-slate-400 mt-1">
              {config.stripe_mock_mode 
                ? 'Payments are simulated. Configure Stripe keys for live payments.'
                : 'Stripe is configured and accepting live payments.'}
            </p>
          </div>
        </div>
      </div>

      {/* Environment Variables Status */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Environment Variables</h2>
        <div className="space-y-3">
          {config.required_env_vars?.map((envVar) => (
            <div key={envVar.name} className="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg">
              <div className="flex items-center gap-3">
                {envVar.configured ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                ) : (
                  <XCircle className="w-5 h-5 text-red-500" />
                )}
                <code className="text-sm text-slate-300">{envVar.name}</code>
              </div>
              <span className={`text-sm ${envVar.configured ? 'text-emerald-400' : 'text-red-400'}`}>
                {envVar.configured ? 'Configured' : 'Missing'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Info */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-6">
        <h3 className="font-medium text-white mb-2">Configuration Instructions</h3>
        <ol className="list-decimal list-inside text-sm text-slate-400 space-y-2">
          <li>Obtain API keys from <a href="https://dashboard.stripe.com" className="text-violet-400 hover:underline" target="_blank" rel="noopener noreferrer">Stripe Dashboard</a></li>
          <li>Set environment variables in your deployment configuration</li>
          <li>Create price IDs for Pro and Enterprise plans in Stripe</li>
          <li>Configure webhook endpoint and secret for subscription events</li>
        </ol>
      </div>
    </div>
  );
}
