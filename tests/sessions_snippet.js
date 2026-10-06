// cogtree viewer 用户会话模拟(v0.11 环版,10 轮,分步执行)
// 反复 evaluate 直到 {done:true,total:0}。每轮:逐个点主干站→钻子节点→悬停→折叠往返→
// 空点清选中→全景点卡开侧栏→环拖拽→展开全部/收纳主干/站点回跳→换树往返。
// 每步断言:中心在场且亮 / 主干站全亮 / 祖先链 / 环孩子在场(compose 几何) / 两两不挡(渐隐豁免) / 无出视口。
(function(){
  var st = window.S;
  if(!st||!st.st) return "no state";
  if(!window.__sess || window.__sess.done){
    window.__sess={problems:[],plan:[],k:0,done:false};
    var problems=window.__sess.problems,plan=window.__sess.plan,se=window.__sess;
    st.noAnim=true;
    var ids=st.st.nodes.map(function(n){return n.id});
    var pmap={};st.st.nodes.forEach(function(n){if(n.parent_id)pmap[n.id]=n.parent_id});
    var rootSteps=ids.filter(function(id){return st.byId[id]&&st.byId[id].kind==="step"&&st.byId[id].parent_id===st.st.root_id});
    if(!rootSteps.length)problems.push("当前树没有主干 step:"+st.cur);
    function rend(){var m={};document.querySelectorAll("g[data-id]").forEach(function(g){m[g.getAttribute("data-id")]=1});return m}
    function opacOf(id){var g=document.querySelector('g[data-id="'+id+'"]');return g?+(g.getAttribute("opacity")||1):null}
    function tfOf(id){var g=document.querySelector('g[data-id="'+id+'"]');if(!g)return null;
      var m=(g.getAttribute("transform")||"").match(/translate\(([-\d.]+),([-\d.]+)\)\s*scale\(([\d.]+),[\d.]+\)/);
      return m?{x:+m[1],y:+m[2],s:+m[3]}:null}
    function expectOp(id){var v=1,c=st.byId[id];while(c){var d2=st.deps&&st.deps[c.id];if(d2!=null)v*=Math.max(0.14,1-0.78*d2);c=c.parent_id?st.byId[c.parent_id]:null}return v}
    function checkAll(tag){
      window.fit();
      var rects=[].map.call(document.querySelectorAll('g[data-id]'),function(g){
        var cr=g.querySelector("rect");if(!cr)return null;var r=cr.getBoundingClientRect();
        return{id:g.getAttribute("data-id"),x:r.x,y:r.y,w:r.width,h:r.height,op:+(g.getAttribute("opacity")||1)};
      }).filter(function(r){return r&&r.w>4});
      rects.forEach(function(r){
        if(r.op<0.6)return;
        if(r.x<-2||r.y<-2||r.x+r.w>window.innerWidth+2||r.y+r.h>window.innerHeight+2)problems.push(tag+": 出视口 "+r.id);
      });
      for(var i=0;i<rects.length;i++)for(var j=i+1;j<rects.length;j++){
        var a=rects[i],b=rects[j];
        if(a.op<0.6||b.op<0.6)continue;
        if((st.rkk&&st.rkk[a.id])<0.97||(st.rkk&&st.rkk[b.id])<0.97)continue; // 环后排(缩放)卡的拥挤是设计内:兜底不推、测试也不算失败
        var ox=Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x),oy=Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y);
        if(ox>4&&oy>4)problems.push(tag+": 卡片互挡 "+a.id+"x"+b.id);
      }
      var r=rend();
      if(st.focus&&st.sel){
        var g=document.querySelector('g[data-id="'+st.sel+'"]');
        if(!g)problems.push(tag+": 聚焦中心未渲染 "+st.sel);
        else if((opacOf(st.sel)||1)<0.85)problems.push(tag+": 聚焦中心太暗 "+st.sel);
      }
      window.render(); // 同步一帧(孤儿/主干/环检查同帧)
      var hid=window.computeVisibility();
      r=rend();
      var pm2={};st.st.nodes.forEach(function(n){if(n.parent_id)pm2[n.id]=n.parent_id}); // 现建父表(换树后 id 同名不同构,用陈旧表会误报孤儿)
      Object.keys(r).forEach(function(id){
        if(id===st.st.root_id)return;
        if(pm2[id]&&!r[pm2[id]])problems.push(tag+": 孤儿卡 "+id);
      });
      if(!st.tidy)rootSteps.forEach(function(s2){if(!r[s2])problems.push(tag+": 主干站缺失 "+s2)});
      Object.keys(st.kidsBy).forEach(function(pid){
        if(hid[pid]||!r[pid]||pid===st.st.root_id)return;
        var ks=st.kidsBy[pid].slice().sort().filter(function(k){return !hid[k]});
        ks.forEach(function(k){if(!r[k]&&expectOp(k)>0.12)problems.push(tag+": 环孩子缺失 "+k)});
        if(ks.length<=3)return;
        var cp=st.cx[pid]||{s:1,tx:0,ty:0};
        ks.forEach(function(k){
          var rp=st.ringPos&&st.ringPos[k],tf=tfOf(k);
          if(!rp||!tf||tf.x==null)return;
          if(Math.abs(tf.x-(cp.s*rp.x+cp.tx))>1.5||Math.abs(tf.y-(cp.s*rp.y+cp.ty))>1.5)problems.push(tag+": 环位置偏 "+k);
        });
      });
    }
    function ckCard(id){var g=document.querySelector('g[data-id="'+id+'"]');if(g)g.dispatchEvent(new MouseEvent("click",{bubbles:true}))}
    function ck(sel){var el=document.querySelector(sel);if(el)el.dispatchEvent(new MouseEvent("click",{bubbles:true}))}
    function visKids(id){var hid=window.computeVisibility();return (st.kidsBy[id]||[]).slice().sort().filter(function(k){return !hid[k]&&st.pos[k]})}

    for(var ses=0;ses<10;ses++){
      (function(ses){
        var T=(ses*2+1)%Math.max(1,rootSteps.length);
        var rotS=0.35+0.15*(ses%4);
        plan.push(function(){st.expandAll=false;st.tidy=false;st.focus=true;st.sel=null;st.sibRot={};st.open={};window.render();checkAll("S"+ses+"-开局")});
        [0,1,2,3,4].forEach(function(k){
          plan.push(function(){
            if(!rootSteps.length)return;
            var t=rootSteps[(T+k)%rootSteps.length];
            ckCard(t);
            if(st.sel!==t)problems.push("S"+ses+": 点主干未选中 "+t);
            checkAll("S"+ses+"-站"+t);
          });
        });
        plan.push(function(){var d=visKids(st.sel)[0]||null;if(d)ckCard(d);checkAll("S"+ses+"-钻入")});
        plan.push(function(){se.hoverId=(document.querySelector("g[data-id]")||{getAttribute:null}).getAttribute?document.querySelector("g[data-id]").getAttribute("data-id"):null});
        plan.push(function(){
          var g=se.hoverId&&document.querySelector('g[data-id="'+se.hoverId+'"]');
          if(!g){se.hoverTries=0;return}
          g.dispatchEvent(new MouseEvent("mouseenter"));
          var hv=document.getElementById("hover");
          if(!hv||hv.style.display!=="block"){se.hoverTries=(se.hoverTries||0)+1;if(se.hoverTries<6){se.waiting=true;return}problems.push("S"+ses+": 悬停浮卡没出");se.hoverTries=0;return}
          se.hoverTries=0;g.dispatchEvent(new MouseEvent("mouseleave"));
        });
        plan.push(function(){ // 点节点展开/收起往返
          var hid=window.computeVisibility();
          var cand=(st.kidsBy[st.sel]||[]).slice().sort().filter(function(k){return !hid[k]})[0]||null;
          if(!cand||!(st.kidsBy[cand]||[]).length)return;
          var before=document.querySelectorAll("g[data-id]").length;
          ckCard(cand);
          if(!st.open[cand])problems.push("S"+ses+": 点节点没展开 "+cand);
          ckCard(cand);
          if(st.open[cand])problems.push("S"+ses+": 再点没收起 "+cand);
          if(document.querySelectorAll("g[data-id]").length!==before)problems.push("S"+ses+": 收展卡数没回到原值");
          checkAll("S"+ses+"-展开往返");
        });
        plan.push(function(){
          document.getElementById("stage").dispatchEvent(new MouseEvent("click",{bubbles:true}));
          if(st.sel)problems.push("S"+ses+": 空点没清选中 "+st.sel);
          checkAll("S"+ses+"-空点");
        });
        plan.push(function(){
          var n0=document.querySelectorAll("g[data-id]").length;
          ck("#fab");checkAll("S"+ses+"-FAB展开");
          if(!st.expandAll||document.querySelectorAll("g[data-id]").length<n0)problems.push("S"+ses+": FAB展开无效");
          var r=rend(),pick=null;
          for(var k in r){if(k!==st.st.root_id&&st.byId[k]&&(opacOf(k)||1)>=0.9){pick=k;break}}
          if(pick){ckCard(pick);checkAll("S"+ses+"-展开态点卡");
            var pn=document.getElementById("panel");
            if(pn&&pn.style.display==="block")problems.push("S"+ses+": 聚焦下不应弹侧栏");
          }
          ck("#fab");
          if(st.expandAll)problems.push("S"+ses+": FAB收纳无效");
          checkAll("S"+ses+"-FAB收纳");
        });
        plan.push(function(){ // 环拖拽
          var pid=null,best=0;
          Object.keys(st.kidsBy).forEach(function(p){var n=st.kidsBy[p].length;if(p!==st.st.root_id&&n>best&&n>3){best=n;pid=p}});
          if(pid==null)return;
          var prevX={},prevS={};
          [0.2,rotS,0.75,1.2].forEach(function(sv){
            st.sibRot[pid]=sv;window.render();
            st.kidsBy[pid].slice().sort().forEach(function(c){
              var tf=(function(){var g=document.querySelector('g[data-id="'+c+'"]');if(!g)return null;
                var m=(g.getAttribute("transform")||"").match(/translate\(([-\d.]+),/);return m?+m[1]:null})();
              if(tf!=null&&prevX[c]!=null&&prevS[c]!=null&&Math.abs(tf-prevX[c])>1250*Math.abs(sv-prevS[c])+30)problems.push("S"+ses+": 环拖大跳 "+c); // 按步距归一(背面峰值≈1186px/单位s)
              if(tf!=null){prevX[c]=tf;prevS[c]=sv}
            });
          });
          st.sibRot[pid]=Math.round(rotS);window.render();
          checkAll("S"+ses+"-环拖");
        });
        plan.push(function(){if(!st.expandAll)ck("#fab");checkAll("S"+ses+"-展开全部")});
        plan.push(function(){if(st.expandAll)ck("#fab");checkAll("S"+ses+"-收纳回聚焦");
          var r=rend();var station=Object.keys(r).filter(function(k){return k!==st.st.root_id})[0];
          if(station){ckCard(station);checkAll("S"+ses+"-站点回跳")}
        });
        plan.push(function(){
          var sel=document.getElementById("treesel"),cur=st.cur,other=null;
          for(var i=0;i<sel.options.length;i++)if(sel.options[i].value!==cur){other=sel.options[i].value;break}
          if(!other){se.origTree=null;se.otherTree=null;return}
          se.origTree=cur;se.otherTree=other;se.settle=0;
          sel.value=other;sel.onchange&&sel.onchange();
        });
        plan.push(function(){
          if(se.otherTree==null)return;
          if(st.cur!==se.otherTree){se.waiting=true;return}
          se.settle=(se.settle||0)+1;
          if(se.settle<3){se.waiting=true;return}
          se.settle=0;
          if(Object.keys(rend()).length<1)problems.push("S"+ses+": 换树后无渲染");
          checkAll("S"+ses+"-换树");
          var sel=document.getElementById("treesel");
          sel.value=se.origTree;sel.onchange&&sel.onchange();
        });
        plan.push(function(){
          if(se.origTree==null)return;
          if(st.cur!==se.origTree){se.waiting=true;return}
          se.settle=(se.settle||0)+1;
          if(se.settle<3){se.waiting=true;return}
          se.settle=0;
          checkAll("S"+ses+"-换回");
          se.origTree=null;se.otherTree=null;
        });
      })(ses);
    }
    plan.push(function(){st.focus=true;st.sel=null;window.render()});
  }
  var se=window.__sess;
  window.__sessStep=function(budget){
    while(budget-->0){
      if(se.k>=se.plan.length){se.done=true;break}
      var k0=se.k;se.waiting=false;
      try{se.plan[se.k]()}catch(e){se.problems.push("EXC#"+se.k+" "+String(e).slice(0,80));se.k++;continue}
      if(se.waiting){
        se.waits=(se.waits||0)+1;
        if(se.waits<=8){se.k=k0;break}
        se.problems.push("WAIT超时 step#"+se.k);se.waits=0;se.k++;continue;
      }
      se.waits=0;se.k++;
      if(se.problems.length>8){se.k=se.plan.length;break}
    }
    if(se.k>=se.plan.length)se.done=true;
    return {done:se.done,total:se.problems.length,sample:se.problems.slice(0,8),progress:se.k+"/"+se.plan.length};
  };
  return window.__sessStep(8);
})()
