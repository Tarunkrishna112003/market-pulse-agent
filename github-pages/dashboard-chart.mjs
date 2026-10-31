const NS='http://www.w3.org/2000/svg';
function svgNode(tag,attrs={}){const node=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));return node;}

export function sparkline(history,{width=120,height=36,id='spark',filled=false}={}){
 const values=history.map(d=>Array.isArray(d)?d[1]:d.close).filter(Number.isFinite).slice(-30);
 const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,class:'sparkline','aria-hidden':'true'});
 if(values.length<2)return svg;
 const min=Math.min(...values),max=Math.max(...values),color=values.at(-1)>=values[0]?'#3a9a71':'#c77468',span=max-min||1;
 const points=values.map((v,i)=>[i/(values.length-1)*width,height-4-(v-min)/span*(height-9)]);
 const path=points.map((p,i)=>(i?'L':'M')+p.join(',')).join(' ');
 if(filled)svg.append(svgNode('path',{d:path+` L${width},${height} L0,${height} Z`,fill:color,opacity:'.07'}));
 svg.append(svgNode('path',{d:path,fill:'none',stroke:color,'stroke-width':'1.6','stroke-linejoin':'round'}));return svg;
}

export function priceChart(days,label){
 const shell=document.createElement('div');shell.className='chart-shell';
 const points=days.filter(d=>Number.isFinite(d.close)&&d.close>0);
 const svg=svgNode('svg',{viewBox:'0 0 1000 300',class:'price-chart',role:'img','aria-label':label,tabindex:'0'});
 const tooltip=document.createElement('div');tooltip.className='chart-tooltip';tooltip.hidden=true;
 if(!points.length){shell.textContent='No price history is available in this window.';return shell;}
 const left=10,right=925,top=18,bottom=220,min=Math.min(...points.map(d=>d.close)),max=Math.max(...points.map(d=>d.close)),pad=(max-min)*.12||1,lo=min-pad,hi=max+pad;
 const X=i=>left+i/Math.max(points.length-1,1)*(right-left),Y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
 const color=points.at(-1).close>=points[0].close?'#268966':'#c46e60';
 for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4,y=Y(value);svg.append(svgNode('line',{x1:left,x2:right,y1:y,y2:y,stroke:'#edf1ed','stroke-dasharray':'3 5'}));const text=svgNode('text',{x:942,y:y+3,class:'chart-axis'});text.textContent='$'+value.toFixed(2);svg.append(text);}
 const d=points.map((point,i)=>(i?'L':'M')+X(i)+','+Y(point.close)).join(' ');
 svg.append(svgNode('path',{d:d+` L${X(points.length-1)},${bottom} L${left},${bottom} Z`,fill:color,opacity:'.055'}));
 svg.append(svgNode('path',{d,fill:'none',stroke:color,'stroke-width':'2','stroke-linecap':'round','stroke-linejoin':'round'}));
 const maxVolume=Math.max(1,...points.map(p=>Number.isFinite(p.volume)?p.volume:0));
 for(let i=0;i<points.length;i++){const v=points[i].volume;if(!Number.isFinite(v)||v<0)continue;const h=v/maxVolume*28;svg.append(svgNode('rect',{x:X(i)-1,y:260-h,width:Math.max(1,(right-left)/points.length*.6),height:h,fill:(points[i].change||0)>=0?'#cce4d7':'#eed8d1',rx:'.5'}));}
 const marks=[0,Math.round((points.length-1)/3),Math.round((points.length-1)*2/3),points.length-1];
 for(const i of new Set(marks)){const text=svgNode('text',{x:X(i),y:285,class:'chart-axis','text-anchor':i===0?'start':i===points.length-1?'end':'middle'});text.textContent=points[i].date;svg.append(text);}
 const crosshair=svgNode('line',{y1:top,y2:263,stroke:'#88a693','stroke-dasharray':'3 3',visibility:'hidden'}),dot=svgNode('circle',{r:4,fill:color,stroke:'#fff','stroke-width':2,visibility:'hidden'});svg.append(crosshair,dot);
 let current=points.length-1;
 function inspect(i){current=Math.max(0,Math.min(points.length-1,i));const p=points[current];crosshair.setAttribute('x1',X(current));crosshair.setAttribute('x2',X(current));crosshair.setAttribute('visibility','visible');dot.setAttribute('cx',X(current));dot.setAttribute('cy',Y(p.close));dot.setAttribute('visibility','visible');tooltip.replaceChildren();tooltip.append(document.createTextNode('$'+p.close.toFixed(2)));const date=document.createElement('small');date.textContent=p.date+' · closing price';tooltip.append(date);tooltip.hidden=false;}
 svg.addEventListener('pointermove',event=>{const rect=svg.getBoundingClientRect(),x=(event.clientX-rect.left)/rect.width*1000;inspect(Math.round((x-left)/(right-left)*(points.length-1)))});
 svg.addEventListener('pointerleave',()=>{tooltip.hidden=true;crosshair.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden')});
 svg.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();inspect(event.key==='Home'?0:event.key==='End'?points.length-1:current+(event.key==='ArrowLeft'?-1:1))}});
 shell.append(svg,tooltip);return shell;
}
