'use client';

import dynamic from 'next/dynamic';

const GeoSpatialFlowTwin = dynamic(
  () => import('./GeoSpatialFlowTwin'),
  { ssr: false }
);

type GeoSpatialFlowTwinProps = {
  scenarioId?: string;
  focusNodeId?: string;
  focusLabel?: string;
  onDisruptionApply?: (sim: unknown) => void;
};

export default function GeoSpatialFlowTwinLoader(props: GeoSpatialFlowTwinProps) {
  return <GeoSpatialFlowTwin {...props} />;
}
