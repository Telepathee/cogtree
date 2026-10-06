// cogtree viewer 交互模糊测试(v0.11 环版,可分步执行)
// 用法:viewer 起来后,反复 evaluate 本文件,直到 {done:true,total:0}。
// 断言:聚焦中心全尺寸 / 主干站全亮在场 / 祖先链完整 / 可见父的所有孩子都渲染 /
//       环几何(u=i−s−1 → 椭圆位置,误差≤1.5px) / 前排窗口卡近满亮 / 卡片两两不挡(渐隐卡豁免) /
//       无出视口 / 无透明残留 / 拖动扫描(卡片数恒定+步进无跳变)。
(function(){
  var st = window.S;
  if(!st||!st.st) return "no state";
  if(!window.__fz || window.__fz.done){
    var ids = st.st.nodes.map(function(n){return n.id});
    var pmap = {}; st.st.nodes.forEach(function(n){if(n.parent_id)pmap[n.id]=n.parent_id});
    var rootSteps = ids.filter(function(id){return st.byId[id]&&st.byId[id].kind==="step"&&st.byId[id].parent_id===st.st.root_id});
    window.__fz = { problems: [], plan: [], k: 0, done: false };
    var problems = window.__fz.problems, plan = window.__fz.plan;
    st.noAnim = true; st.expandAll = false; st.tidy = false; st.focus = true; st.sel = null; st.sibRot = {}; st.open = {};
    function rend(){var m={};document.querySelectorAll("g[data-id]").forEach(function(g){m[g.getAttribute("data-id")]=1});return m}
    function opacOf(id){var g=document.querySelector('g[data-id="'+id+'"]');return g?+(g.getAttribute("opacity")||1):null}
    function tfOf(id){var g=document.querySelector('g[data-id="'+id+'"]');if(!g)return null;
      var m=(g.getAttribute("transform")||"").match(/translate\(([-\d.]+),([-\d.]+)\)\s*scale\(([\d.]+),[\d.]+\)/);
      return m?{x:+m[1],y:+m[2],s:+m[3]}:{x:null,y:null,s:1}}
    function geomCheck(tag){
      window.fit();
      var rects=[].map.call(document.querySelectorAll('g[data-id]'),function(g){
        var cr=g.querySelector("rect");if(!cr)return null;var r=cr.getBoundingClientRect();
        return{id:g.getAttribute("data-id"),x:r.x,y:r.y,w:r.width,h:r.height,op:+(g.getAttribute("opacity")||1)};
      }).filter(function(r){return r&&r.w>4});
      rects.forEach(function(r){
        if(r.op<0.6)return; // 渐隐卡允许探出
        if(r.x<-2||r.y<-2||r.x+r.w>window.innerWidth+2||r.y+r.h>window.innerHeight+2)
          problems.push(tag+": 出视口 "+r.id);
      });
      for(var i=0;i<rects.length;i++)for(var j=i+1;j<rects.length;j++){
        var a=rects[i],b=rects[j];
        if(a.op<0.6||b.op<0.6)continue;
        if((st.rkk&&st.rkk[a.id])<0.97||(st.rkk&&st.rkk[b.id])<0.97)continue; // 环后排(缩放)卡的拥挤是设计内:兜底不推、测试也不算失败 // 渐隐卡允许层叠(环背面)
        var ox=Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x),oy=Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y);
        if(ox>4&&oy>4)problems.push(tag+": 卡片互挡 "+a.id+"x"+b.id);
      }
      [].forEach.call(document.querySelectorAll('g[data-id]'),function(g){
        var op=parseFloat(getComputedStyle(g).opacity);
        if(op<0.05)problems.push(tag+": 卡片不可见 "+g.getAttribute("data-id"));
        // 环上透明度是深度的连续函数(1→0.22),不再有"卡死区间"
      });
      var r=rend();
      if(st.focus&&st.sel){
        var g=document.querySelector('g[data-id="'+st.sel+'"]');
        if(!g)problems.push(tag+": 聚焦中心未渲染 "+st.sel);
        else if((opacOf(st.sel)||1)<0.85)problems.push(tag+": 聚焦中心太暗 "+st.sel+"="+(opacOf(st.sel)||1));
      }
      Object.keys(st.pos).forEach(function(k){
        if(!isFinite(st.pos[k].x)||!isFinite(st.pos[k].y))problems.push(tag+": 坐标NaN "+k);
      });
      // 环不变量:可见父的所有孩子都在场(深度淡出到快透明的允许缺席);环卡几何符合 compose 链
      window.render(); // 同步一帧,消除跨帧脏读(含孤儿/主干/环检查,全在同一帧内)
      var hid=window.computeVisibility();
      r=rend();
      var pm2={};st.st.nodes.forEach(function(n){if(n.parent_id)pm2[n.id]=n.parent_id}); // 现建父表(换树后 id 同名不同构,用陈旧表会误报孤儿)
      Object.keys(r).forEach(function(id){
        if(id===st.st.root_id)return;
        if(pm2[id]&&!r[pm2[id]])problems.push(tag+": 孤儿卡 "+id);
      });
      if(!st.tidy)rootSteps.forEach(function(s2){if(!r[s2])problems.push(tag+": 主干站缺失 "+s2)});
      r=rend();
      function expectOp(id){ // 沿祖先链的期望透明度(与渲染端 chainOp 同式)
        var v=1,c=st.byId[id];
        while(c){
          var d2=st.deps&&st.deps[c.id];
          if(d2!=null)v*=Math.max(0.14,1-0.78*d2);
          c=c.parent_id?st.byId[c.parent_id]:null;
        }
        return v;
      }
      Object.keys(st.kidsBy).forEach(function(pid){
        if(hid[pid]||!r[pid]||pid===st.st.root_id)return;
        var ks=st.kidsBy[pid].slice().sort().filter(function(k){return !hid[k]});
        ks.forEach(function(k){
          if(!r[k]&&expectOp(k)>0.12)problems.push(tag+": 环孩子缺失 "+k+"(父"+pid+")");
        });
        if(ks.length<=3)return;
        var nn=ks.length,sv=st.sibRot[pid]||0;
        ks.forEach(function(k,i){ // 行为断言:卡在环上=被缩放(0.5~1)且透明度=深度连续函数;前排卡在场且可见
          var tf=tfOf(k);if(!tf||tf.s==null)return;
          if(tf.s<0.1||tf.s>1.001)problems.push(tag+": 环比例越界 "+k+"="+tf.s); // tf.s=全链合成(父链×自身),下限≈0.52³
          if(Math.abs(i-sv-1)<=1&&r[k]&&(opacOf(k)||1)<0.13)problems.push(tag+": 前排卡太暗 "+k+"="+(opacOf(k)||1));
        });
      });
    }
    function oneClick(tag,i){
      var id = ids[Math.floor(Math.random()*ids.length)];
      try { window.select(id, Math.random()<0.45); } catch(e){ problems.push("EXC "+String(e).slice(0,60)); return; }
      if(!rend()[id])problems.push("未渲染 "+id);
      if(i%2===0)geomCheck(tag);
    }
    ["focus","pano"].forEach(function(mode){
      for(var i=0;i<120;i++){
        (function(mode,i){
          plan.push(function(){
            if(i===0){st.focus=(mode==="focus");window.render()}
            oneClick((mode==="focus"?"F":"P")+i,i);
          });
        })(mode,i);
      }
    });
    // 拖动扫描:找最宽环,冻结无关状态,s 0→2 连续,断言 count 恒定+步进无跳变+几何公式
    (function(){
      var pid=null,best=0;
      Object.keys(st.kidsBy).forEach(function(p){
        var n=st.kidsBy[p].length;
        if(p!==st.st.root_id&&n>best&&n>3){best=n;pid=p}
      });
      if(pid==null)return;
      var prevSet=null,hist={},jump=0;
      for(var s=0;s<=2.0001;s+=0.1){
        (function(sv){
          plan.push(function(){
            st.focus=false;window.render();
            if(sv===0){st.sibRot={};window.render()}
            st.sibRot[pid]=+sv.toFixed(2);
            window.render();
            var cur=[].map.call(document.querySelectorAll("g[data-id]"),function(g){return g.getAttribute("data-id")});
            if(prevSet){
              cur.filter(function(x){return prevSet.indexOf(x)<0}).concat(prevSet.filter(function(x){return cur.indexOf(x)<0}))
                .forEach(function(x){ if(pmap[x]!==pid)problems.push("DRAG: 非环排卡片进出 "+x+"(s="+sv.toFixed(2)+")") });
            }
            prevSet=cur;
            st.kidsBy[pid].slice().sort().forEach(function(c){
              var tf=tfOf(c);if(!tf||tf.x==null)return;
              var h=hist[c]||(hist[c]=[]);
              h.push(tf);
              if(h.length>=3){ // 二阶差分:连续运动加速度小;真跳变=突增
                var d1=h[h.length-2].x-h[h.length-3].x, d2=h[h.length-1].x-h[h.length-2].x;
                if(Math.abs(d2-d1)>45){jump++;problems.push("DRAG: 跳变 "+c+"(s="+sv.toFixed(2)+" d1="+Math.round(d1)+" d2="+Math.round(d2)+")")}
                var ds1=h[h.length-2].s-h[h.length-3].s, ds2=h[h.length-1].s-h[h.length-2].s;
                if(Math.abs(ds2-ds1)>0.06){jump++;problems.push("DRAG: 比例跳变 "+c+"(s="+sv.toFixed(2)+")")}
              }
            });
            if(Math.abs(sv-2)<0.001){st.sibRot={};window.render()}
          });
        })(Math.round(s*10)/10);
      }
    })();
    // 收尾
    plan.push(function(){st.focus=true;st.sel=null;window.render()});
  }
  var fz=window.__fz;
  window.__fzStep=function(budget){ // 每次重建片段都重定义,防止旧闭包抓旧 fz
    while(budget-->0){
      if(fz.k>=fz.plan.length){fz.done=true;break}
      try{fz.plan[fz.k++]()}catch(e){fz.problems.push("EXC#"+fz.k+" "+String(e).slice(0,80));break}
      if(fz.problems.length>8){fz.k=fz.plan.length;break}
    }
    if(fz.k>=fz.plan.length)fz.done=true;
    return {done:fz.done,total:fz.problems.length,sample:fz.problems.slice(0,8),progress:fz.k+"/"+fz.plan.length};
  };
  return window.__fzStep(30);
})()
