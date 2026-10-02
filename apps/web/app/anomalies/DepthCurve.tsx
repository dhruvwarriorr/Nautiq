// Small server-rendered scientific figure; depths increase downwards.
export default function DepthCurve({depths, curves, label}: {depths: number[]; curves: {label: string; values: (number | null)[]; color: string}[]; label: string}) {
  const valid = curves.flatMap(c => c.values.filter((v): v is number => v != null));
  if (!valid.length) return <p>No supported curve values.</p>;
  const low = Math.min(0,...valid), high = Math.max(0,...valid), span = high-low || 1;
  const x = (v: number) => 70+(v-low)/span*310, y = (z: number) => 25+(z-depths[0])/(depths[depths.length-1]-depths[0])*310;
  return <figure className="depth-curve"><svg viewBox="0 0 450 390" role="img" aria-label={label}>
    {[0,1,2,3,4].map(i => <g key={i}><path d={`M 70 ${25+i*77.5} H 380`} stroke="#ccd8d4"/><text x="60" y={29+i*77.5} textAnchor="end" fontSize="12">{Math.round(depths[0]+(depths[depths.length-1]-depths[0])*i/4)}</text><text x={70+i*77.5} y="358" textAnchor="middle" fontSize="12">{(low+span*i/4).toFixed(2)}</text></g>)}
    <path d={`M ${x(0)} 25 V 335`} stroke="#82958e" strokeDasharray="4 4"/>
    <text x="16" y="190" transform="rotate(-90 16 190)" textAnchor="middle" fontSize="12">Depth (m)</text>
    {curves.map(c => {let path=""; let previous=false; for(let i=0;i<depths.length;i++){const v=c.values[i]; if(v == null){previous=false;continue;} path+=`${previous?" L":" M"} ${x(v).toFixed(2)} ${y(depths[i]).toFixed(2)}`; previous=true;} return <path key={c.label} d={path} fill="none" stroke={c.color} strokeWidth="2"/>;})}
  </svg><figcaption>{curves.map(c => <span key={c.label} style={{color:c.color}}>{c.label} · </span>)}{label}</figcaption></figure>;
}
