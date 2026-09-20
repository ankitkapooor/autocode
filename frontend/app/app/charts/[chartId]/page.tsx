import { ChartWorkspace } from "@/components/chart-workspace";

export default async function ChartPage({ params }: { params: Promise<{ chartId: string }> }) {
  const { chartId } = await params;
  return <ChartWorkspace chartId={chartId} />;
}
