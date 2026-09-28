// Schwarzschild *optical-metric* ray integration in isotropic coordinates.
// The metric is static / nonrotating; `spin` changes disk beaming and texture,
// not frame dragging. No claim of a full Kerr GRMHD simulation is made.
// Isotropic radius rho: horizon a=M/2, areal R=rho(1+a/rho)^2.
// Null rays obey Fermat's principle in the refractive medium
// n(rho)=(1+a/rho)^3/(1-a/rho).
// With Euclidean arclength s, dT/ds = grad(log n) - T(T dot grad(log n)).
// Midpoint (RK2) integration near the photon sphere produces multiple images
// of the rear disk and a physically motivated shadow, without a fake ring mask.
export const blackholeFragment = `precision highp float;
uniform vec2 resolution;
uniform float time;
uniform float progress;
uniform float orbit;
uniform float tilt;
uniform float spin;
uniform float lens;
uniform float fly;
uniform int mode;
const float a = .12; // M/2; isotropic horizon radius
const float mass = 2.0*a;
const float isco = a*(5.0+2.0*sqrt(6.0)); // R_isco = 6M
float hash(vec3 p){return fract(sin(dot(p,vec3(127.1,311.7,74.7)))*43758.5453);}
float noise(vec3 p){vec3 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
vec3 starfield(vec3 d){
vec3 cell=floor(normalize(d)*320.0);
float star=step(.976,hash(cell));
// Multi-scale stellar dust and blue-violet nebula; all sampled from the bent
// ray's escape direction, so the starfield is actually lensed by the metric.
float fine=pow(noise(d*210.0),13.0);
float cloud=noise(d*5.0+vec3(13.,2.,7.))*noise(d*11.0);
float nebula=smoothstep(.28,.70,cloud);
float temp=hash(cell+vec3(30.,70.,10.));
vec3 colour=mix(vec3(1.0,.53,.28),vec3(.54,.74,1.0),temp);
return vec3(.014,.025,.058)+star*colour*1.75+fine*vec3(.21,.32,.5)+nebula*vec3(.08,.11,.20);
}
vec3 bend(vec3 p, vec3 t){
float r=max(length(p),a+.018);
float derivative=-3.0*a/(r*(r+a))-a/(r*(r-a));
vec3 grad=(lens/1.8)*derivative*p/r;
return grad-t*dot(t,grad);
}
vec3 diskEmission(vec3 hit, vec3 direction, vec3 normal){
float r=length(hit);
float R=r*pow(1.0+a/r,2.0);
float inner=isco*pow(1.0+a/isco,2.0);
float radial=pow(max(inner/R,.01),.75)*pow(max(0.0,1.0-sqrt(inner/R)),.25);
float phi=atan(hit.z,hit.x);
float swirl=noise(vec3(phi*9.0-time*(.15+spin*.35), r*17.0, r*4.0));
float veins=.64+.65*swirl+.17*sin(r*47.0-phi*6.0-time*(.4+spin));
vec3 tangent=normalize(cross(normal,hit));
float speed=min(.65,sqrt(mass/max(R-2.0*mass,.2)))*(.45+.55*spin);
float gamma=1.0/sqrt(1.0-speed*speed);
float doppler=1.0/(gamma*max(.45,1.0-speed*dot(tangent,-direction)));
float gravity=sqrt(max(.03,1.0-2.0*mass/R));
float shifted=clamp(doppler*gravity, .55, 1.65);
vec3 warm=mix(vec3(.95,.17,.014),vec3(1.95,1.0,.37),clamp((shifted-.6)/.9,0.0,1.0));
float edge=smoothstep(isco,isco+.16,r)*(1.0-smoothstep(2.65,3.15,r));
return warm*radial*veins*pow(doppler,3.0)*edge*4.1;
}
void main(){
vec2 uv=(gl_FragCoord.xy-.5*resolution)/resolution.y;
float angle=time*orbit*.35;
vec3 ro=vec3(5.7*sin(angle),.32,5.7*cos(angle));
if(mode==1){
float travel=clamp(progress*(.55+fly),0.0,1.0);
float dist=mix(5.7,.24,travel*travel*(3.0-2.0*travel));
ro=vec3(.16*dist,.045*dist,dist);
}
if(mode==2) ro=vec3(2.2*sin(angle),.20,5.5*cos(angle));
vec3 forward=normalize(-ro), right=normalize(cross(forward,vec3(0.,1.,0.))), up=cross(right,forward);
vec3 rd=normalize(forward*1.65+right*uv.x+up*uv.y);
vec3 pos=ro, hdr=vec3(0.);
float transmittance=1.0;
float closest=length(ro);
float diskAngle=radians(tilt);
vec3 normal=normalize(vec3(0.,cos(diskAngle),sin(diskAngle)));
bool trapped=false;
for(int i=0;i<190;i++){
float r=length(pos);
closest=min(closest,r);
if(r <= a*1.025){trapped=true;break;}
if(r>9.0 && dot(pos,rd)>0.0)break;
// Adaptive arclength; shrink steps near horizon and photon sphere.
float ds=clamp((r-a)*.075,.008,.16);
vec3 k1=bend(pos,rd);
vec3 midDir=normalize(rd+k1*ds*.5);
vec3 midPos=pos+rd*ds*.5;
vec3 next=pos+midDir*ds;
vec3 newDir=normalize(rd+bend(midPos,midDir)*ds);
if(mode!=2 && dot(pos,normal)*dot(next,normal)<=0.0){
float frac=abs(dot(pos,normal))/(abs(dot(pos,normal))+abs(dot(next,normal))+.000001);
vec3 hit=mix(pos,next,frac);
float radius=length(hit);
if(radius>isco && radius<3.15){
vec3 emission=diskEmission(hit,rd,normal);
// Disk is optically semi-transparent, allowing rear secondary images.
float opacity=clamp(length(emission)*.24,.0,.82);
hdr+=transmittance*emission*.85;
transmittance*=1.0-opacity;
}
}
pos=next;
rd=newDir;
}
if(!trapped){
hdr+=transmittance*starfield(rd);
if(mode==2){
// Scattered dust around strongly deflected escaping rays, accentuating the
// critical curve without treating it as a screen-space decorative circle.
float photon=a*(2.0+sqrt(3.0));
hdr+=vec3(.045,.10,.20)*exp(-abs(closest-photon)*3.5);
}
}
// Filmic shoulder retains hot accretion colours without clipping to pure white.
vec3 mapped=(hdr*(2.51*hdr+.03))/(hdr*(2.43*hdr+.59)+.14);
mapped=clamp(mapped,0.0,1.0);
float vignette=1.0-.26*smoothstep(.25,1.35,length(uv));
if(mode==1) mapped*=1.0-.72*smoothstep(.93,1.0,progress);
gl_FragColor=vec4(pow(mapped*vignette,vec3(.86)),1.0);
}`;
