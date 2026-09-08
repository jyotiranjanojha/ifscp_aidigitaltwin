'use client';

import dynamic from 'next/dynamic';

const PlannerCockpit = dynamic(() => import('@/src/components/PlannerCockpit'), { ssr: false });

export default function Page() {
  return <PlannerCockpit />;
}