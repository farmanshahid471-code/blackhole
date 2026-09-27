import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';

// Original, reusable vector primitives: no source footage, logos or sampled art.
const C = {night:'#071a28', deep:'#0b2835', teal:'#49d7bd', pale:'#dff5ed', coral:'#f87961', gold:'#f5c878', muted:'#8eb4b7'};
const ease = (n:number) => Math.max(0,Math.min(1,n));
const mix = (a:number,b:number,t:number) => a+(b-a)*ease(t);
const stars = Array.from({length:68},(_,i)=>({
  x:24+((i*197+41)%1230),y:22+((i*i*73+113)%680),r:.6+((i*7)%4)*.3,
}));
const arc = (r:number,a:number,b:number) => {
  const x=(t:number)=>640+r*Math.cos(t),y=(t:number)=>350+r*Math.sin(t);
  return `M${x(a)} ${y(a)} A${r} ${r} 0 ${b-a>Math.PI?1:0} 1 ${x(b)} ${y(b)}`;
};
const bg = <><rect width="1280" height="720" fill={C.night}/><path d="M0 560 Q350 410 650 610 T1280 510 V720 H0Z" fill={C.deep} opacity=".42"/>
  {stars.map((s,i)=><circle key={i} cx={s.x} cy={s.y} r={s.r} fill={C.pale} opacity={.22+(i%4)*.12}/>)}</>;
const Label: React.FC<{kicker:string;title:string;detail:string}> = ({kicker,title,detail}) => <g fontFamily="Arial, sans-serif">
  <rect x="56" y="55" width="37" height="5" rx="2" fill={C.teal}/>
  <text x="109" y="68" fill={C.teal} fontSize="19" fontWeight="700" letterSpacing="5">FIELD NOTES  /  {kicker}</text>
  <text x="57" y="137" fill={C.pale} fontSize="45" fontWeight="700" letterSpacing="1">{title}</text>
  <text x="58" y="666" fill={C.muted} fontSize="21" letterSpacing="1.2">{detail}</text>
</g>;
const marks = (f:number,fps:number,duration:number) => <g>
  <rect x="58" y="688" width="1164" height="3" fill="#305360"/>
  <rect x="58" y="688" width={1164*ease(f/(duration*fps))} height="3" fill={C.teal}/>
</g>;

export type VectorShot = 'stellar_equilibrium'|'stellar_collapse'|'horizon_boundary';
export const VectorShotScene: React.FC<{shot:VectorShot;duration:number}> = ({shot,duration}) => {
  const frame=useCurrentFrame(),{fps}=useVideoConfig(),t=frame/fps;
  const entering=interpolate(frame,[0,Math.round(.45*fps)],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  const leaving=interpolate(frame,[Math.round((duration-.5)*fps),Math.round(duration*fps)],[1,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  const alpha=Math.min(entering,leaving);
  const p=ease(t/duration);
  const pulse=Math.sin(t*4.5);
  return <AbsoluteFill style={{background:C.night,opacity:alpha}}><svg width="100%" height="100%" viewBox="0 0 1280 720" preserveAspectRatio="xMidYMid meet" role="img" aria-label={shot.replace(/_/g,' ')}>
    {bg}
    {shot==='stellar_equilibrium'&&<>
      <Label kicker="01" title="A STAR HOLDS ITS GROUND" detail="Outward energy and inward gravity hold a temporary balance."/>
      <g transform={`translate(640 365) rotate(${t*4})`}>
        {[0,1,2].map((i)=><circle key={i} r={120+i*21+Math.sin(t*3+i)*3} fill="none" stroke={i===0?C.gold:C.coral} strokeWidth={i===0?18:3} opacity={.7-i*.2}/>)}
        <circle r={106+pulse*2} fill={C.coral}/><circle r="73" fill={C.gold}/><circle r="34" fill="#fff5cf"/>
        {Array.from({length:10},(_,i)=>{const a=i*Math.PI/5+t*.14;return <g key={i} transform={`rotate(${a*180/Math.PI})`}><path d="M154 -7 L195 0 L154 7" fill="none" stroke={C.gold} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/></g>;})}
      </g>
      {Array.from({length:6},(_,i)=>{const a=i*Math.PI/3+.1, r=345-19*(t%3);return <g key={i} transform={`translate(${640+Math.cos(a)*r} ${365+Math.sin(a)*r}) rotate(${a*180/Math.PI+180})`}><path d="M-14 -8 L0 0 L-14 8" fill="none" stroke={C.teal} strokeWidth="4"/></g>;})}
      <rect x="72" y="321" width="230" height="124" rx="14" fill="#0f3340" stroke="#2b5c63"/>
      <text x="92" y="362" fill={C.gold} fontFamily="Arial" fontSize="22" fontWeight="bold">OUTWARD ENERGY</text>
      <text x="92" y="403" fill={C.teal} fontFamily="Arial" fontSize="22" fontWeight="bold">INWARD GRAVITY</text>
    </>}
    {shot==='stellar_collapse'&&<>
      <Label kicker="02" title="WHEN THE FUEL RUNS LOW" detail="An illustrative collapse — not a simulation of a particular star."/>
      {(()=>{const shrink=ease((t-1.1)/3.1),burst=ease((t-4.1)/2),radius=mix(145,26,shrink);return <>
        {[0,1,2,3].map((i)=><circle key={i} cx="640" cy="354" r={radius+37+i*25} fill="none" stroke={i%2?C.teal:C.coral} opacity={.75-i*.13} strokeWidth={5-i*.65} strokeDasharray={`${20+i*9} ${18+i*7}`} transform={`rotate(${t*(i%2?22:-18)} 640 354)`}/>)}
        {Array.from({length:18},(_,i)=>{const a=i*Math.PI/9,dist=50+burst*(205+(i%4)*42),flare=burst>.05;return <g key={i} opacity={flare?1-burst*.47:0} transform={`translate(${640+Math.cos(a)*dist} ${354+Math.sin(a)*dist}) rotate(${a*180/Math.PI})`}><path d="M-16 -4 L14 0 L-16 4Z" fill={i%3?C.coral:C.gold}/></g>;})}
        <circle cx="640" cy="354" r={radius} fill={burst>.3?C.night:C.coral} stroke={burst>.3?C.teal:C.gold} strokeWidth="7"/>
        <circle cx="640" cy="354" r={radius*.53} fill={burst>.3?C.night:C.gold} opacity=".85"/>
        {burst>.05&&<circle cx="640" cy="354" r={40+burst*260} fill="none" stroke={C.gold} strokeWidth={8*(1-burst)} opacity={1-burst}/>}
        <text x="72" y="344" fill={C.muted} fontFamily="Arial" fontSize="22" letterSpacing="2">FUSION FADES</text>
        <path d="M76 361 H285" stroke={C.coral} strokeWidth="4" strokeDasharray={`${210*(1-shrink)} 210`}/>
        <text x="72" y="414" fill={C.teal} fontFamily="Arial" fontSize="22" letterSpacing="2">GRAVITY WINS</text>
        <path d="M76 431 H285" stroke={C.teal} strokeWidth="4" strokeDasharray={`${210*shrink} 210`}/>
      </>})()}
    </>}
    {shot==='horizon_boundary'&&<>
      <Label kicker="03" title="A BOUNDARY FOR LIGHT" detail="Light can bend around the horizon; this diagram is not a ray-tracing simulation."/>
      {Array.from({length:4},(_,i)=><path key={i} d={arc(129+i*20,-2.8,2.7)} fill="none" stroke={i%2?C.gold:C.teal} strokeWidth={i?2:6} opacity={.65-i*.1} strokeDasharray={`${(arc(129+i*20,-2.8,2.7).length+780)*ease((t-.5)/4)} 2000`} transform={`rotate(${t*3+i*41} 640 350)`}/>)}
      <circle cx="640" cy="350" r="148" fill="none" stroke={C.teal} strokeWidth="2" strokeDasharray="9 15" opacity=".7"/>
      <circle cx="640" cy="350" r="123" fill={C.night} stroke={C.coral} strokeWidth="6"/>
      <circle cx="640" cy="350" r="108" fill="#020b15"/>
      {[-2,-1,0,1,2].map((i)=>{
        const sign=Math.sign(i), level=Math.abs(i)-1;
        // The central beam ends at the horizon; the others bend around it, never through it.
        const startY=350+sign*(112+level*52), bendY=350+sign*(178+level*17);
        const path=i===0?'M190 350 H516':`M190 ${startY} C410 ${startY}, 430 ${bendY}, 640 ${bendY} S920 ${startY}, 1090 ${startY}`;
        return <path key={i} d={path} fill="none" opacity={ease((t-.5-i*.12)/1.1)} stroke={i===0?C.gold:C.teal} strokeWidth={i===0?4:2} strokeDasharray={`${Math.max(0,t*185-i*40)} 1400`}/>;
      })}
      <path d="M736 427 L883 513 H1090" stroke={C.gold} strokeWidth="2" fill="none"/>
      <circle cx="736" cy="427" r="5" fill={C.gold}/>
      <text x="899" y="508" fill={C.gold} fontFamily="Arial" fontSize="23" fontWeight="bold">EVENT HORIZON</text>
      <text x="69" y="368" fill={C.teal} fontFamily="Arial" fontSize="21" letterSpacing="1">LIGHT PATHS</text>
    </>}
    {marks(frame,fps,duration)}
  </svg></AbsoluteFill>;
};

export const VectorPilot:React.FC=()=>{
  const {fps}=useVideoConfig();
  return <AbsoluteFill style={{background:C.night}}>
    <Sequence from={0} durationInFrames={8*fps}><VectorShotScene shot="stellar_equilibrium" duration={8}/></Sequence>
    <Sequence from={8*fps} durationInFrames={8*fps}><VectorShotScene shot="stellar_collapse" duration={8}/></Sequence>
    <Sequence from={16*fps} durationInFrames={8*fps}><VectorShotScene shot="horizon_boundary" duration={8}/></Sequence>
  </AbsoluteFill>;
};
