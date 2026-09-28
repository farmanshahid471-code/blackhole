import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

const panel: React.CSSProperties = {width:'100%',height:'100%',background:'radial-gradient(ellipse at 50% 45%, #12243a, #050b17 75%)',color:'#e8f0fc',fontFamily:'Arial, sans-serif',position:'relative',overflow:'hidden'};
const label: React.CSSProperties = {fontSize:32,fontWeight:700,letterSpacing:5,textTransform:'uppercase',color:'#f6b566'};
const fade = (f: number, start: number, end: number) => interpolate(f,[start,end],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
export const Diagram: React.FC<{shot:string; params:Record<string,any>; title:string}> = ({shot, params, title}) => {
  const frame = useCurrentFrame(); const {width,height,fps} = useVideoConfig();
  const s = Math.min(width/1920,height/1080);
  const p = fade(frame, 4, fps*1.4);
  if(shot==='title_card'||shot==='outro') return <div style={{...panel,display:'flex',flexDirection:'column',justifyContent:'center',alignItems:'center'}}>
    <div style={{width:200*s,height:2,background:'#d69247',marginBottom:35*s}}/>
    <div style={{fontSize:82*s,fontWeight:800,letterSpacing:8*s,textAlign:'center',maxWidth:'75%',opacity:p,transform:`translateY(${(1-p)*30}px)`}}>{title || (shot==='outro'?'THE UNIVERSE AWAITS':'BEYOND THE HORIZON')}</div>
    <div style={{...label,fontSize:22*s,marginTop:40*s,opacity:p}}>A SPACE DOCUMENTARY</div></div>;
  const cx=width*.5,cy=height*.48;
  if(shot==='core_cross_section_diagram'){
    const focus=params.highlight || 'singularity';
    return <div style={panel}><svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <defs><radialGradient id="core"><stop stopColor="#050a11"/><stop offset="75%" stopColor="#060913"/><stop offset="100%" stopColor="#d98b40"/></radialGradient></defs>
      {[290,210,135].map((r,i)=><circle key={r} cx={cx} cy={cy} r={r*s} fill={i===2?'url(#core)':'none'} stroke={focus===['photon_sphere','event_horizon','singularity'][i]?'#ffd28a':'#4d7c9a'} strokeWidth={(i===2?5:2)*s} strokeDasharray={`${Math.round(2*Math.PI*r*s*p)} 9999`} />)}
      {(['PHOTON SPHERE','EVENT HORIZON','SINGULARITY'] as const).map((name,i)=><g key={name} opacity={fade(frame, fps*(i+.4),fps*(i+1))}><line x1={cx+([290,210,135][i])*s} y1={cy} x2={cx+390*s} y2={cy+(i-1)*120*s} stroke="#e4a760" strokeWidth={2*s}/><text x={cx+400*s} y={cy+(i-1)*120*s+8*s} fill="#f4d9b3" fontSize={29*s} letterSpacing={3*s}>{name}</text></g>)}
      <text x={90*s} y={130*s} fill="#f3b770" fontSize={42*s} letterSpacing={5*s}>ANATOMY OF A BLACK HOLE</text>
    </svg></div>;
  }
  if(shot==='mass_scale_compare'){
    const bars=[['OUR SUN',.16,'#efd294'],['STELLAR BLACK HOLE',.44,'#ed9b54'],['SUPERMASSIVE BLACK HOLE',.86,'#d46a4a']];
    return <div style={{...panel,padding:`${90*s}px ${120*s}px`,boxSizing:'border-box'}}><div style={{...label,fontSize:45*s,marginBottom:90*s}}>A QUESTION OF SCALE</div>
      {bars.map(([name,v,color],i)=><div key={name} style={{marginBottom:64*s,opacity:fade(frame, fps*i*.65, fps*(i*.65+.5))}}><div style={{fontSize:27*s,letterSpacing:3*s,marginBottom:18*s}}>{name}</div><div style={{height:45*s,width:`${Number(v)*p*95}%`,background:color,boxShadow:`0 0 ${24*s}px ${color}`,borderRadius:4}}/></div>)}
      <div style={{opacity:.55,fontSize:22*s}}>ILLUSTRATIVE COMPARISON · NOT TO SCALE</div></div>;
  }
  if(shot==='two_perspectives_split') return <div style={{...panel,display:'flex',flexDirection:'column'}}>
    {['THE DISTANT OBSERVER','THE FALLING TRAVELER'].map((name,i)=><div key={name} style={{height:'50%',boxSizing:'border-box',position:'relative',borderBottom:i===0?'2px solid #4f657f':'none',display:'flex',justifyContent:'space-around',alignItems:'center',opacity:fade(frame,i*fps*.6, i*fps*.6+15)}}><div style={{...label,fontSize:28*s,width:'34%',textAlign:'center'}}>{name}</div><div style={{fontSize:130*s,color:i===0?'#ba4949':'#f1bd78',transform:`translateY(${i===1?p*70*s:0}px)`}}>✦</div><div style={{fontSize:25*s,letterSpacing:2*s,width:'35%',textAlign:'center'}}>{i===0?'LIGHT REDSHIFTS · TIME SLOWS':'CROSSING FEELS ORDINARY'}</div></div>)}</div>;
  // Stylized tidal stretching, intentionally diagrammatic rather than astrophysical simulation.
  return <div style={{...panel,display:'flex',justifyContent:'center',alignItems:'center'}}><div style={{...label,position:'absolute',top:85*s,fontSize:40*s}}>TIDAL FORCES</div>
    <div style={{width:260*s,height:260*s,borderRadius:'50%',background:'#05080e',boxShadow:`0 0 ${65*s}px 12px #bb632c`,position:'absolute',left:'15%'}}/>
    <div style={{width:220*s/(1+p*params.stretch),height:120*s*(1+p*params.stretch),borderRadius:'50%',background:'linear-gradient(90deg,#fbd49b,#e88950)',boxShadow:`0 0 ${36*s}px #e88b4e`,transform:`translateX(${-p*300*s}px) rotate(-80deg)`}}/></div>;
};
