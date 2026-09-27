import React from 'react';
import {AbsoluteFill, Composition, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import library from '../shots.json';
import {SpaceShader} from './shots/SpaceShader';
import {Diagram} from './shots/Graphics';

type Scene = {shot:string; params:Record<string,any>; title?:string; text_overlays?:Array<{t:number;text:string;style:string}>;duration:number};
type Props = {scene: Scene; width:number;height:number;fps:number};
const fallback: Props = {scene:{shot:'accretion_disk_orbit',params:{},title:'THE GRAVITY TRAP',duration:10,text_overlays:[]},width:1920,height:1080,fps:30};
const Visual: React.FC<Props> = ({scene}) => {
  const frame=useCurrentFrame(),{fps,width,height}=useVideoConfig();
  if(!(scene.shot in library)) throw new Error(`Unknown shot: ${scene.shot}`);
  const shaderMode=scene.shot==='accretion_disk_orbit'?'disk':scene.shot==='event_horizon_flythrough'?'fly':scene.shot==='starfield_warp'?'warp':null;
  return <AbsoluteFill style={{background:'#050b17'}}>
    {shaderMode?<SpaceShader mode={shaderMode} params={scene.params||{}} duration={scene.duration}/>:<Diagram shot={scene.shot} params={scene.params||{}} title={scene.title||''}/>}
    {(scene.text_overlays||[]).map((overlay,i)=>{
      const start=Math.round(overlay.t*fps), alpha=interpolate(frame,[start,start+12],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
      return <div key={i} style={{position:'absolute',left:'10%',right:'10%',top:overlay.style==='lower_third'?'73%':'15%',textAlign:overlay.style==='lower_third'?'left':'center',opacity:alpha,color:'#f9f4e9',fontFamily:'Arial, sans-serif',fontWeight:800,letterSpacing:5,fontSize:(overlay.style==='lower_third'?45:76)*Math.min(width/1920,height/1080),textShadow:'0 3px 28px #000'}}>{overlay.text}</div>;
    })}
  </AbsoluteFill>;
};
export const Root: React.FC = () => <Composition id="Scene" component={Visual} durationInFrames={300} fps={30} width={1920} height={1080} defaultProps={fallback}
  calculateMetadata={({props})=>({durationInFrames:Math.max(1,Math.round(props.scene.duration*props.fps)),fps:props.fps,width:props.width,height:props.height})}/>;
