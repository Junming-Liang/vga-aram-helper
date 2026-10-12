'use strict';
// Three reviewable slots. Every edit invalidates in-flight comparisons.
(function initChoices(){
  const inputs=[0,1,2].map(i=>$(`choice-${i}`));
  const status=$('choice-status'), result=$('choice-result'), compare=$('compare-choices');
  let generation=0, controller=null, busy=false;
  const values=()=>inputs.map(input=>input.value.trim());
  function problem(){
    if(!data)return '资料还在加载。';
    if(!hero)return '先从左侧选择英雄。';
    const offered=values();
    if(offered.some(name=>!name))return '请填满三个候选，再确认比较。';
    if(new Set(offered).size!==3)return '三个候选不能重复，请核对名称。';
    const unknown=offered.filter(name=>!data.augments[name]);
    return unknown.length?'名称未收录：'+unknown.join('、'):'三个名称均已匹配。请核对与游戏一致，再点击比较。';
  }
  function valid(){return !!data&&!!hero&&values().every(name=>data.augments[name])&&new Set(values()).size===3;}
  function refresh(){compare.disabled=busy||!valid();status.textContent=problem();}
  function invalidate(){generation++;if(controller)controller.abort();controller=null;busy=false;result.innerHTML='';refresh();}
  inputs.forEach(input=>input.addEventListener('input',invalidate));
  document.addEventListener('vga:hero-changed',invalidate);
  function loadOptions(){
    if(!data)return;
    $('augment-options').innerHTML=Object.keys(data.augments).sort(collator.compare).map(name=>`<option value="${escapeText(name)}"></option>`).join('');
    refresh();
  }
  document.addEventListener('vga:data-ready',loadOptions);
  if(typeof data!=='undefined'&&data)loadOptions();
  $('clear-choices').addEventListener('click',()=>{inputs.forEach(input=>input.value='');invalidate();document.dispatchEvent(new CustomEvent('vga:round-cleared'));inputs[0].focus();});
  window.VGAChoices={
    fillOffered(names){
      if(!Array.isArray(names)||names.length!==3)return false;
      inputs.forEach((input,i)=>{input.value=String(names[i]||'');});invalidate();
      status.textContent='OCR 候选已填入，请核对左、中、右三个名称，再点击比较。';return true;
    },
    addCandidate(name){
      if(values().includes(name)){status.textContent='该候选已在三项中，请勿重复加入。';return false;}
      const slot=inputs.find(input=>!input.value.trim());
      if(!slot){status.textContent='三项已填满。请手动修改对应位置，或点击换一轮。';return false;}
      slot.value=name;invalidate();return true;
    },
    invalidate,
    clear(){inputs.forEach(input=>input.value='');invalidate();},
  };
  function display(response){
    const synthetic=data.metadata.isDemo;
    const official=response.policy==='official-hero-source-order-v1';
    const sourceTitle=synthetic?'虚构演示统计':official?'官方英雄专属统计':'英雄资料依据';
    result.innerHTML=`<div class="comparison-summary"><span class="eyebrow">${escapeText(hero)} · ${sourceTitle}</span><h3>${escapeText(response.decision)}</h3><p class="muted">${escapeText(response.policyExplanation)}</p></div><div class="comparison-cards">${response.cards.map(card=>{
      const observed=card.numGames===0?'0（未有样本）':Number.isFinite(card.numGames)?card.numGames.toLocaleString('zh-CN'):'未提供';
      const notes=[...card.positiveEvidence.map(note=>`<p class="rule-note">英雄说明：${escapeText(note.reason||'来源未给理由')}</p>`),...card.trapEvidence.map(note=>`<p class="notice error">陷阱提醒：${escapeText(note.reason||'来源未给理由')}</p>`)];
      return `<article class="comparison-card ${response.recommendedName===card.name?'preferred':''}"><div class="card-top"><span class="badge">原选项 ${card.slot}</span>${card.officialRank?`<span class="muted">源顺位 #${card.officialRank}</span>`:''}</div><h3>${escapeText(card.name)}</h3>${response.recommendedName===card.name?'<span class="badge">优先考虑</span>':''}${card.officialStats?`<span class="badge">源评级 ${escapeText(card.tier||'未提供')}</span><dl class="pair-stats"><div><dt>该英雄 + 海克斯胜率</dt><dd>${rate(card.pairWinRate)}</dd></div><div><dt>源配对选取率</dt><dd>${rate(card.pickRate)}</dd></div><div><dt>源样本量</dt><dd>${observed}</dd></div></dl>${card.pairWinRate===null?'<p class="notice">来源未提供有效配对胜率，不能视为 0%。</p>':''}`:'<p class="notice">当前数据没有该英雄与此海克斯的配对统计。未收录不代表弱。</p>'}${card.category!=='unknown'?`<p class="muted">${escapeText(card.label)}</p>`:''}${notes.join('')}${card.conditionFlags.length||card.cautionFlags.length?'<p class="notice">说明中存在条件或风险用语，请阅读原文；软件没有判断这些条件已经满足。</p>':''}${card.matchingTags.length?`<p class="tiny">重合标签：${escapeText(card.matchingTags.join('、'))}（不作硬性限制）</p>`:''}<details><summary>全局参考与来源</summary><p class="tiny">海克斯全局参考值：${rate(card.globalReferenceWinRate)}。不参与本次英雄排序。</p><p class="tiny">${escapeText(card.globalRateNote)}</p></details></article>`;
    }).join('')}</div><p class="tiny">${escapeText((response.warnings||[]).join(' '))}</p>`;
  }
  compare.addEventListener('click',async()=>{
    if(!valid())return refresh();
    const current=++generation, selectedHero=hero, offered=values();
    if(controller)controller.abort();controller=new AbortController();busy=true;compare.disabled=true;result.innerHTML='';status.textContent='正在比较该英雄的三个候选…';
    try{
      const response=await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hero:selectedHero,offered}),signal:controller.signal});
      const payload=await response.json();
      if(current!==generation||selectedHero!==hero||JSON.stringify(offered)!==JSON.stringify(values()))return;
      if(!response.ok)throw new Error(payload.error||'比较失败');
      display(payload);status.textContent='比较完成。修改英雄或任一候选后，需重新确认。';
    }catch(error){if(current===generation&&error.name!=='AbortError')status.textContent=error.message||'比较暂时失败，请重试。';}
    finally{if(current===generation){busy=false;compare.disabled=!valid();}}
  });
})();

(function initUpdates(){
  const status=$('update-status'), install=$('install-update');let available=null;
  async function poll(){
    try{
      const response=await fetch('/api/status');if(!response.ok)throw new Error();
      const payload=await response.json(), source=payload.data||{}, software=payload.software||{};
      status.textContent=`软件 v${payload.applicationVersion||'未知'} · 数据：${source.message||source.state||'未知'} ${source.sourceDataDate?'源数据日期 '+source.sourceDataDate+'。':''} ${source.fetchedAt?'获取时间 '+source.fetchedAt+'（不代表统计更新日）。':''} 软件更新：${software.message||software.state||'未知'}`;
      available=software.canInstall&&software.release?software.release:null;
      install.hidden=!available;
      if(available)install.textContent=`查看并安装 v${available.version}`;
      if(software.state==='checking')setTimeout(poll,1500);
    }catch(_){status.textContent='暂时无法读取更新状态；请确认本地服务仍在运行。';}
  }
  install.addEventListener('click',async()=>{
    if(!available)return;
    const release=available;
    if(!window.confirm(`安装 VGA乱斗助手 v${release.version}？\n将从项目官方 GitHub Release 下载并校验，当前程序会关闭并重启。\n\n${release.notes||'该版本未提供更新说明。'}`))return;
    install.disabled=true;
    try{
      const response=await fetch('/api/updates/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,version:release.version})});
      const payload=await response.json();if(!response.ok)throw new Error(payload.error||'更新准备失败');
      status.textContent=payload.message;install.hidden=true;
    }catch(error){status.textContent=error.message;install.disabled=false;}
  });
  poll();
})();
