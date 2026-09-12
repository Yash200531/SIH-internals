interface StatCardProps {
  title: string;
  value: number;
  trend?: string;
}

export function StatCard({ title, value, trend }: StatCardProps) {
  return (
    <div className="bg-white rounded-lg border p-4">
      <p className="text-sm text-gray-500">{title}</p>
      <p className="text-3xl font-bold text-primary mt-1">{value}</p>
      {trend && <p className="text-xs text-gray-400 mt-1">{trend}</p>}
    </div>
  );
}
