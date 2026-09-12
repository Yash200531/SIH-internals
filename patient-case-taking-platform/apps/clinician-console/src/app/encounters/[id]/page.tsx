export default async function EncounterDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-primary">Encounter {id}</h1>
      <p className="text-gray-500">Encounter detail view — review and sign</p>
    </div>
  );
}
