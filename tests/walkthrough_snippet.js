// cogtree viewer 日常操作走查片段(v1.0.4)
// 用法:viewer 起来后,evaluate 本文件内容(async),返回 {ok, errs, steps}。
// 走查:悬浮钮展开/收纳(默认聚焦) / 折叠按钮 / 点卡选中 / 空点 / 悬停浮卡 / 换树往返。
(async function(){
  var S = window.S;
  if(!S||!S.st) return "no state";
  var errs = [];
  window.addEventListener("error", function(e){ errs.push(String(e.message).slice(0,90)) });
  var steps = [];
  var wait = function(ms){ return new Promise(function(r){ setTimeout(r, ms) }) };
  function clickEl(sel){ var el=document.querySelector(sel); if(!el)return false;
    el.dispatchEvent(new MouseEvent("click",{bubbles:true})); return true } // SVG 元素没有 .click()
  function cardClick(id){ var g=document.querySelector('g[data-id="'+id+'"]'); if(!g)return false;
    g.dispatchEvent(new MouseEvent("click",{bubbles:true})); return true }
  function cardCount(){ return document.querySelectorAll("g[data-id]").length }
  var S0 = { expandAll:S.expandAll, cur:S.cur, sel:S.sel };

  // 1. 五个旧按钮已移除,只剩悬浮钮
  ["focus","pano","expand","tidy","fit"].forEach(function(id){
    steps.push("旧按钮"+id+"已删:"+(!document.getElementById(id)));
  });
  steps.push("默认聚焦:"+(S.expandAll===false&&document.querySelectorAll("g[data-id]").length<S.st.nodes.length));

  // 2. 悬浮钮:点一下全展开,再点一下回聚焦(收纳)
  var n0=cardCount();
  clickEl("#fab");
  var n1=cardCount();
  steps.push("FAB展开:"+(S.expandAll===true&&n1>=S.st.nodes.length-1&&document.getElementById("fab").textContent==="收纳"));
  clickEl("#fab");
  steps.push("FAB收纳:"+(S.expandAll===false&&cardCount()===n0&&document.getElementById("fab").textContent==="展开"));

  // 3. 点节点=展开一层/再点收起(先点一个主干站把它的子代带出来,再在其中找一个真能多出卡的节点试)
  if(!S.expandAll){ var sts=[];
    for(var rp in S.kidsBy){ var k2=S.byId[rp]; if(k2&&k2.kind==="step"&&rp!==S.st.root_id&&document.querySelector('g[data-id="'+rp+'"]'))sts.push(rp); }
    if(sts.length)cardClick(sts[0]);
  }
  var cands=[];
  for(var pid in S.kidsBy){
    var ks=S.kidsBy[pid],n2=S.byId[pid];
    if(ks&&ks.length&&n2&&n2.kind!=="step"&&!S.expandAll&&document.querySelector('g[data-id="'+pid+'"]'))cands.push(pid);
  }
  for(var ci=0;ci<cands.length;ci++){
    var cand=cands[ci],before=cardCount();
    cardClick(cand);
    if(cardCount()<=before){ continue; } // 该节点的孩子本来就常显,换下一个
    steps.push("点节点展开 "+cand+":"+(!!S.open[cand]));
    var kids=S.kidsBy[cand].slice().sort();
    var gk=(S.kidsBy[kids[0]]||[]).length; // 只开一层:再看它孩子的孩子不该全出来
    cardClick(cand);
    steps.push("再点收起 "+cand+":"+(!S.open[cand]&&cardCount()===before));
    break;
  }

  // 4. 点卡选中 + 空点清除
  var anyId=null;
  document.querySelectorAll("g[data-id]").forEach(function(g){ if(!anyId)anyId=g.getAttribute("data-id") });
  if(anyId){
    cardClick(anyId);
    steps.push("点卡选中:"+(S.sel===anyId));
  }
  document.getElementById("stage").dispatchEvent(new MouseEvent("click",{bubbles:true}));
  steps.push("空点清选中:"+(S.sel===null||S.sel!==anyId));

  // 5. 悬停浮卡
  var hg=document.querySelector("g[data-id]");
  if(hg){ hg.dispatchEvent(new MouseEvent("mouseenter")); await wait(260);
    var hv=document.getElementById("hover");
    steps.push("悬停浮卡:"+(hv&&hv.style.display==="block"));
    hg.dispatchEvent(new MouseEvent("mouseleave"));
  }

  // 6. 换树再切回
  var sel=document.getElementById("treesel");
  var other=null;
  for(var i=0;i<sel.options.length;i++){ if(sel.options[i].value!==S.cur){other=sel.options[i].value;break} }
  if(other){
    sel.value=other; sel.onchange&&sel.onchange();
    await wait(900);
    steps.push("换树:"+(S.cur===other&&cardCount()>0));
    steps.push("换树后复位展开态:"+(S.expandAll===false));
    sel.value=S0.cur; sel.onchange&&sel.onchange();
    await wait(900);
    steps.push("切回原树:"+(S.cur===S0.cur));
  }
  window.render();
  var bad = steps.filter(function(s){return /:false/.test(s)});
  return { ok: bad.length===0 && errs.length===0, errs: errs, steps: steps };
})()
