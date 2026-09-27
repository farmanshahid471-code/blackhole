import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';
import timing from '../narrated-timing.json';
import {VectorShotScene, type VectorShot} from './VectorPilot';
import {SpaceShader} from './SpaceShader';

const WarpCue: React.FC = () => {
  const frame=useCurrentFrame();
  const length=timing.duration_frames-timing.shader_start_frame;
  const fade=interpolate(frame,[0,12],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
  return <AbsoluteFill style={{opacity:fade}}>
    <SpaceShader mode="warp" params={{lens_strength:1.5}} duration={length/timing.fps} renderScale={0.35}/>
    <div style={{position:'absolute',top:64,left:64,color:'#dff5ed',font:'bold 39px Arial, sans-serif',letterSpacing:3,textShadow:'0 2px 8px #000'}}>LIGHT IN CURVED SPACETIME</div>
  </AbsoluteFill>;
};

/** Visual-only voice-driven timeline. FFmpeg muxes the voice and burns aligned ASS captions. */
export const NarratedPilot: React.FC = () => {
  const {fps} = useVideoConfig();
  if (fps !== timing.fps) throw new Error('Narrated pilot was aligned at 24 fps');
  return <AbsoluteFill style={{background:'#071a28'}}>
    {timing.scenes.map((scene) => <Sequence key={scene.id} from={scene.start_frame} durationInFrames={scene.duration_frames}>
      <VectorShotScene shot={scene.shot as VectorShot} duration={scene.duration_frames/fps}/>
    </Sequence>)}
    <Sequence from={timing.shader_start_frame} durationInFrames={timing.duration_frames-timing.shader_start_frame}>
      <WarpCue/>
    </Sequence>
  </AbsoluteFill>;
};
export const narratedPilotFrames = timing.duration_frames;
