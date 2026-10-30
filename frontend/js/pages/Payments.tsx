import { Fragment, useEffect, useState } from 'react';

import { client } from '@/js/api/client.gen';
import type { Payment } from '@/js/api';
import { TopNav } from '@/js/components';

const maskReference = (reference?: string | null) => {
  if (!reference) return '—';
  return reference.length <= 12 ? reference : `${reference.slice(0, 7)}…${reference.slice(-4)}`;
};

const amountUsd = (minor: number) => `$${(minor / 100).toFixed(2)}`;

const statusClasses: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  succeeded: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-rose-100 text-rose-800',
};

const Payments = () => {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    async function fetchPayments() {
      const response = await client.instance.get<Payment[]>('/api/payments');
      setPayments(response.data);
      setLoading(false);
    }
    fetchPayments();
  }, []);

  return (
    <>
      <TopNav />
      <section className="mx-auto max-w-4xl px-4">
        <h1 className="mt-4 mb-3 text-2xl font-semibold text-slate-950">Payments</h1>
        <p className="mb-4 text-sm text-slate-600">
          Read-only view. Only masked instrument and processor references are shown.
        </p>

        {loading ? (
          <p className="text-slate-600">Loading…</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-zinc-300 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 text-slate-600">
                <tr>
                  <th className="px-4 py-2 font-medium">Amount</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Instrument</th>
                  <th className="px-4 py-2 font-medium">Processor ref</th>
                  <th className="px-4 py-2 font-medium">Ledger</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((payment) => (
                  <Fragment key={payment.id}>
                    <tr className="border-t border-zinc-200">
                      <td className="px-4 py-3 font-mono text-slate-900">
                        {amountUsd(payment.amount_minor)} {payment.currency}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            statusClasses[payment.status] ?? 'bg-slate-100 text-slate-700'
                          }`}
                        >
                          {payment.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-700">
                        {payment.method || '—'} ····{payment.last4 || '????'}
                        {payment.brand_or_bank_type ? ` (${payment.brand_or_bank_type})` : ''}
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-500">
                        {maskReference(payment.processor_reference)}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          className="text-emerald-700 hover:underline"
                          type="button"
                          onClick={() => setExpanded(expanded === payment.id ? null : payment.id)}
                        >
                          {expanded === payment.id ? 'Hide' : `${payment.ledger.length} entries`}
                        </button>
                      </td>
                    </tr>
                    {expanded === payment.id && (
                      <tr className="border-t border-zinc-100 bg-zinc-50">
                        <td className="px-4 py-3" colSpan={5}>
                          <ol className="space-y-1 text-xs text-slate-700">
                            {payment.ledger.map((entry) => (
                              <li key={entry.sequence} className="font-mono">
                                #{entry.sequence} {entry.event_type} → {entry.status}
                                {entry.failure_code ? ` (${entry.failure_code})` : ''}
                              </li>
                            ))}
                          </ol>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            {payments.length === 0 && (
              <p className="px-4 py-6 text-center text-slate-500">No payments yet.</p>
            )}
          </div>
        )}
      </section>
    </>
  );
};

export default Payments;
