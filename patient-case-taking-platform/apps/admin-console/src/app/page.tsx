const stats = [
  { label: "Active Users", value: 0 },
  { label: "Facilities", value: 0 },
  { label: "Active Sessions", value: 0 },
];

export default function AdminDashboard() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Admin Dashboard</h1>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {stats.map((s) => (
          <div
            key={s.label}
            className="bg-surface border border-midnight-border rounded-lg p-6"
          >
            <p className="text-sm text-slate-400">{s.label}</p>
            <p className="text-3xl font-bold mt-1">{s.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
