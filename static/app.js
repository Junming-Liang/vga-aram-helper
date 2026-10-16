'use strict';
// Original UI. Source text is always escaped; no external assets or code load.
const $ = id => document.getElementById(id);
const escapeText = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const normalized = value => String(value ?? '').toLocaleLowerCase('zh-CN').replace(/\s/g, '');
const collator = new Intl.Collator('zh-CN');
const nameSort = (a, b) => collator.compare(a.name, b.name);
const rarityNames = {prismatic:'棱彩', gold:'黄金', silver:'白银', unknown:'未分类'};
const storageKey = 'hex-reference-original:favorites:v1';
let data, hero = '', tab = 'augments', favoriteOnly = false, heroLimit = 28, cardLimit = 28, detailGeneration = 0;
let favorites = new Set();
try {
  const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
  if (Array.isArray(saved)) favorites = new Set(saved.filter(x => typeof x === 'string'));
} catch (_) { /* malformed or unavailable storage is harmless */ }
function saveFavorite(kind, name) {
  const key = `${kind}:${name}`;
  favorites.has(key) ? favorites.delete(key) : favorites.add(key);
  try { localStorage.setItem(storageKey, JSON.stringify([...favorites])); }
  catch (_) { $('storage-status').textContent = '浏览器不允许保存，收藏仅在本次页面有效'; }
  renderCards();
}
function favoriteButton(kind, name) {
  const saved = favorites.has(`${kind}:${name}`);
  return `<button class="star ${saved ? 'saved' : ''}" data-favorite="${escapeText(kind)}" data-name="${escapeText(name)}" aria-pressed="${saved}" aria-label="${saved ? '取消收藏' : '收藏'} ${escapeText(name)}">${saved ? '★' : '☆'}</button>`;
}
function grade(value, hero=false) { return (hero ? ['T1','T2','T3','T4','T5'] : ['T1','T2','T3','T4']).includes(value) ? value : '暂无评级'; }
function relation(name, field) { return (data.relations[hero]?.[field] || []).filter(x => x.name === name); }
function badges(name) {
  return `${relation(name, 'specialAugments').length ? '<span class="badge">英雄联动</span>' : ''}${relation(name, 'trapAugments').length ? '<span class="badge danger">英雄陷阱</span>' : ''}`;
}
function renderHeroes() {
  const query = normalized($('hero-search').value), role = $('hero-role').value;
  const list = Object.values(data.heroes).filter(item => (!query || [item.name, ...item.alias].some(x => normalized(x).includes(query))) && (!role || item.position.includes(role) || (role === '辅助' && item.position.some(x => ['软辅','硬辅'].includes(x)))));
  list.sort(nameSort);
  $('hero-count').textContent = `${list.length} 位英雄 · 公开源评级快照`;
  $('heroes').innerHTML = list.length ? list.slice(0,heroLimit).map(item => `<button class="hero-row ${hero === item.name ? 'selected' : ''}" data-hero="${escapeText(item.name)}" aria-pressed="${hero === item.name}"><span class="avatar" aria-hidden="true">${escapeText(item.name.slice(0,1))}</span><span><span class="hero-name">${escapeText(item.name)}</span><span class="hero-role">${escapeText(item.position.slice(0,2).join(' · ')) || '定位未提供'}</span></span><span class="hero-score">${grade(item.overallTier,true)}</span></button>`).join('') : '<div class="empty">没有找到英雄<br>试试名称或别名</div>';
  $('more-heroes').hidden = list.length <= heroLimit;
  $('clear-hero').hidden = !hero;
  $('hero-context').hidden = !hero;
  if (hero) {
    const record = data.heroes[hero], rel = data.relations[hero];
    $('hero-context').innerHTML = `<div class="row"><div><span class="eyebrow">当前手动选择</span><br><strong>${escapeText(hero)}</strong><p>${escapeText(record.position.join(' · '))}</p></div><button data-detail-kind="heroes" data-name="${escapeText(hero)}">查看联动与陷阱 →</button></div><p>${rel?.specialAugments.length || 0} 条联动 · ${rel?.trapAugments.length || 0} 条陷阱说明 · ${data.heroAugmentStats?.[hero]?.length || 0} 条官方英雄海克斯统计</p>`;
  }
}
function getMainList() {
  const query = normalized($('main-search').value);
  let list = tab === 'combinations' ? data.combinations : Object.values(data[tab]);
  list = list.filter(item => (!query || normalized([item.name, item.description, ...(item.alias || [])].join(' ')).includes(query)) && (!favoriteOnly || favorites.has(`${tab}:${item.name}`)));
  if (tab === 'augments') list = list.filter(item => (!$('rarity').value || item.rarity === $('rarity').value) && ($('show-deleted').checked || !item.isDeleted));
  list.sort(nameSort);
  return list;
}
function renderCards() {
  const list = getMainList();
  $('result-count').textContent = `${list.length} 条结果${hero && tab === 'augments' ? ' · 英雄联动与陷阱已标注；未标注不代表无效或安全' : ''}`;
  $('cards').innerHTML = list.length ? list.slice(0,cardLimit).map(item => {
    const chip = tab === 'augments' ? `<span class="rarity ${item.rarity}">${rarityNames[item.rarity]}</span>` : `<span class="badge">${tab === 'items' ? '装备资料' : `${item.combinations.length} 个分支`}</span>`;
    const value = tab === 'augments' ? `<span class="rate">${grade(item.overallTier)}<small>公开源评级</small></span>` : `<span class="muted">${tab === 'items' ? (item.total ? `${escapeText(item.total)} 金币 · 源标价` : '价格未提供') : (item.last_update ? `源更新时间 ${escapeText(item.last_update)}` : '更新时间未提供')}</span>`;
    return `<article class="card"><div class="card-top">${chip}${favoriteButton(tab,item.name)}</div><button class="card-title" data-detail-kind="${tab}" data-name="${escapeText(item.name)}">${escapeText(item.name)}</button><div>${tab === 'augments' ? badges(item.name) : ''}${item.isDeleted ? '<span class="badge danger">源数据标记已移除</span>' : ''}</div><p class="description">${escapeText(item.description || '源资料未提供描述。')}</p><div class="card-bottom">${value}<button class="details-link" data-detail-kind="${tab}" data-name="${escapeText(item.name)}">查看详情 ↗</button></div></article>`;
  }).join('') : '<div class="empty">没有匹配结果<br>可以更换关键词、筛选，或关闭“只看收藏”。</div>';
  $('more-cards').hidden = list.length <= cardLimit;
}
function title(name) { return `<h2 class="detail-title" id="detail-title">${escapeText(name)}</h2>`; }
function linkedBox(link, kind, extra='') {
  const exists = kind === 'combinations' ? data.combinations.some(x=>x.name===link.name) : !!data[kind][link.name];
  return `<div class="link-box">${exists ? `<button data-detail-kind="${kind}" data-name="${escapeText(link.name)}"><strong>${escapeText(link.name)}</strong> ↗</button>` : `<strong>${escapeText(link.name)}</strong><span class="badge warn">条目缺失</span>`}${link.core ? '<span class="badge">源标记核心</span>' : ''}${extra}<p>${escapeText(link.reason || '未提供具体理由')}</p></div>`;
}
function showDialog(markup) {
  $('detail-content').innerHTML = markup;
  if (!$('detail').open) $('detail').showModal();
  $('detail').scrollTop = 0;
}
function closeDialog() { detailGeneration++; $('detail').close(); }
function sourceNotice() {
  if(data.metadata.officialHeroStatistics)return `<div class="notice">官方数据包 ${escapeText(data.metadata.wikiDataVersion || '未知')} · 游戏资料版本 ${escapeText(data.metadata.gamePatch || '未知')}。统计为来源快照，不是实时对局预测。</div>`;
  return data.metadata.isDemo ? '<div class="notice">虚构演示数据：此处所有数值与玩法仅用于测试。</div>' : `<div class="notice">旧参考快照：最新可见日志 ${escapeText(data.metadata.latestChangelogDate || '未知')}。实际统计日期、样本量及当前版本适用性未验证。</div>`;
}
async function openDetail(kind, name) {
  const generation = ++detailGeneration;
  const item = kind === 'combinations' ? data.combinations.find(x=>x.name===name) : data[kind]?.[name];
  if (!item) return;
  let html = title(name) + sourceNotice();
  if (item.description) html += `<p class="detail-description">${escapeText(item.description)}</p>`;
  if (item.tips) html += `<div class="rule-note">${escapeText(item.tips)}</div>`;
  if (kind === 'heroes') {
    const relations = data.relations[name];
    html += `<p class="muted">${escapeText(item.alias.join(' / '))} · ${escapeText(item.position.join(' · '))}</p><p>英雄整体评级：${grade(item.overallTier,true)}</p><div class="notice">${data.heroAugmentStats?.[name]?.length || 0} 条官方英雄海克斯统计。请在首页确认三个候选后比较；仅展示原始评级，保留候选原位置。</div><div class="detail-grid"><section><h3>联动说明</h3>${relations?.specialAugments.map(x=>linkedBox(x,'augments')).join('') || '<p class="muted">暂无已收录联动，不等于没有联动。</p>'}</section><section><h3>陷阱与限制</h3>${relations?.trapAugments.map(x=>linkedBox(x,'augments')).join('') || '<p class="muted">暂无已收录陷阱，不代表全部安全。</p>'}</section></div>`;
  } else if (kind === 'augments') {
    html += `<p class="muted">${escapeText(rarityNames[item.rarity])} · ${escapeText(item.position.join(' · '))}</p><p>公开源评级：${grade(item.overallTier)} · 当前英雄配对评级：${hero ? grade(data.heroAugmentStats?.[hero]?.find(x=>x.augmentName===name)?.tier) : '请先选择英雄'}</p>${item.isDeleted ? '<div class="notice error">源数据标记该海克斯已移除。当前是否可选尚未验证。</div>' : ''}`;
    if (item.limit.length) html += `<p class="muted">源资料限制标签：${escapeText(item.limit.join('、'))}（仅展示，未推断适配性）</p>`;
    if (hero) {
      html += `<h3>与 ${escapeText(hero)} 的关系</h3>` + relation(name,'specialAugments').map(x=>`<div class="rule-note">联动：${escapeText(x.reason || '未提供理由')}</div>`).join('') + relation(name,'trapAugments').map(x=>`<div class="notice error">陷阱：${escapeText(x.reason || '未提供理由')}</div>`).join('');
      if (!relation(name,'specialAugments').length && !relation(name,'trapAugments').length) html += '<p class="muted">暂无这对英雄与海克斯的明确关系记录。</p>';
    }
    html += '<div id="recommendation-result" aria-live="polite"><p class="muted">正在计算本地装备关联…</p></div>';
  } else if (kind === 'items') {
    html += `<p class="muted">源标价：${escapeText(item.total || '未提供')} ${item.total ? '金币' : ''} · 属性标签：${escapeText(item.types.join('、') || '未提供')}</p>`;
  } else {
    html += `<p class="muted">源更新时间：${escapeText(item.last_update || '未提供')}</p><h3>组合海克斯</h3>${item.augments.map(x=>linkedBox(x,'augments')).join('') || '<p class="muted">未提供</p>'}`;
    if (item.items.length) html += '<h3>父组合装备（仅资料展示）</h3>' + item.items.map(x=>linkedBox(x,'items')).join('');
    for (const branch of item.combinations) html += `<h3>${escapeText(branch.name)}</h3><p class="detail-description">${escapeText(branch.description || branch.tips)}</p><p class="muted">源列适用英雄：${escapeText(branch.heros.join('、') || '未提供')}</p>${branch.augments.map(x=>linkedBox(x,'augments')).join('')}${branch.items.map(x=>linkedBox(x,'items')).join('')}`;
    if (!item.combinations.length) html += '<p class="muted">此组合没有分支；父组合装备不参与自动规则评分。</p>';
  }
  showDialog(html);
  if (kind === 'augments') {
    try {
      const response = await fetch(`/api/recommend?augment=${encodeURIComponent(name)}`);
      if (!response.ok) throw new Error('请求失败');
      const result = await response.json();
      if (generation !== detailGeneration || !$('detail').open) return;
      const recommendations = result.recommendations.sort((a,b)=>b.score-a.score||collator.compare(a.name,b.name)).slice(0,8);
      const warningItems = result.warnings.sort((a,b)=>collator.compare(a.name,b.name));
      const renderRecommendation = entry => `<div class="link-box"><span class="score">${entry.score} 规则分</span><button data-detail-kind="items" data-name="${escapeText(entry.name)}"><strong>${escapeText(entry.name)}</strong> ↗</button>${entry.core ? '<span class="badge">源标记核心</span>' : ''}${entry.warning ? '<span class="badge danger">另有陷阱，先核对</span>' : ''}<ul class="evidence">${entry.evidence.map(e=>`<li>${escapeText(e.source)} · ${e.score} 分${e.reason ? `<br>${escapeText(e.reason)}` : ' · 未提供具体理由'}</li>`).join('')}</ul></div>`;
      $('recommendation-result').innerHTML = `<h3>装备关联 · 前 ${recommendations.length} 项</h3><p class="rule-note">规则分只是资料关联强度，不是胜率，也不随所选英雄变化。直接列表 100；特殊联动 94；组合分支核心 34 / 普通 18，分支匹配 +10、父组合匹配 +5。同一装备取最高分，不相加。</p>${recommendations.map(renderRecommendation).join('') || '<p class="muted">没有可用的装备关联，暂不推测。</p>'}<h3>陷阱装备 · 单独列出</h3>${warningItems.map(renderRecommendation).join('') || '<p class="muted">暂无已收录陷阱，不代表全部安全。</p>'}${result.missingItems.length ? `<p class="notice">${result.missingItems.length} 条关联缺少装备条目，未参与推荐：${escapeText(result.missingItems.join('、'))}</p>` : ''}`;
    } catch (_) {
      if (generation === detailGeneration && $('detail').open) $('recommendation-result').innerHTML = '<div class="notice error">装备关联暂时读取失败。请确认本地服务器仍在运行，再重新打开。</div>';
    }
  }
}
function showAbout() {
  detailGeneration++;
  const m = data.metadata;
  showDialog(title('数据来源与使用边界') + sourceNotice() + `<p class="detail-description">${escapeText(m.source || '来源未提供')}</p><ul class="plain-list"><li>这是独立实现的英雄三选一助手，截图 OCR 在本机运行。尚无实时游戏采集、游戏悬浮层或自动选择。</li><li>三选一保留候选原位置，仅展示英雄配对原始评级；缺失评级不推测。不展示胜率或唯一最佳指令。</li><li>装备规则分可逐条解释。相同装备取最高分而非求和；独立保留陷阱。规则不推断英雄适配。</li><li>同分按浏览器的中文名称顺序排列，最多展示 8 项装备。关联缺失时明确提示。</li><li>仅本机提供服务，不加载外部图片、字体或脚本，不上传收藏。收藏保存在当前浏览器，清理浏览器数据会丢失。</li><li>${escapeText(m.licenseNote || '请自行确认导入数据的使用权限。')}</li></ul>${m.sourceUrl === 'https://gametool.huya.com/lolhex' ? '<p><a href="https://gametool.huya.com/lolhex" target="_blank" rel="noreferrer noopener">手动打开公开参考来源 ↗</a></p>' : ''}<p class="tiny">导入时间：${escapeText(m.importedAt || '内置原创演示')}。导入时间不代表数据更新时间。</p>`);
}
function updateTab() {
  document.querySelectorAll('[data-tab]').forEach(button=>{const active=button.dataset.tab===tab;button.classList.toggle('active',active);button.setAttribute('aria-pressed',active);});
  $('rarity').hidden = tab !== 'augments'; $('deleted-control').hidden = tab !== 'augments';
  $('main-search').placeholder = {augments:'搜索海克斯名称或效果',items:'搜索装备名称、别名或效果',combinations:'搜索组合名称或说明'}[tab];
  renderCards();
}
function bindSearch(id, callback) {
  let composing = false;
  $(id).addEventListener('compositionstart',()=>{composing=true;});
  $(id).addEventListener('compositionend',()=>{composing=false;callback();});
  $(id).addEventListener('input',()=>{if(!composing)callback();});
}
async function init() {
  try {
    const response = await fetch('/api/data'); if (!response.ok) throw new Error('data request failed');
    data = await response.json();
    const m = data.metadata;
    $('source-banner').innerHTML = m.isDemo ? '<strong>演示模式</strong> · 原创虚构样例，不可用于真实对局。' : m.officialHeroStatistics ? `<strong>官方英雄统计</strong> · 数据包 ${escapeText(m.wikiDataVersion || '未知')} / 游戏资料版本 ${escapeText(m.gamePatch || '未知')}。源数据日期 ${escapeText(m.sourceDataDate || '未知')}；获取时间不代表数据更新时间。${m.updateStatus?.state==='cached' ? '当前使用上次成功缓存，请查看下方更新状态。' : m.updateStatus?.state==='fresh' ? '本次启动已检查数据。' : '使用显式本地快照，在线版本未检查。'}配对统计不是实时预测。` : '<strong>官方英雄统计未就绪</strong> · 当前只有参考资料或没有可用数据，不能假装给出官方三选一评分。';
    bindSearch('hero-search',()=>{heroLimit=28;renderHeroes();});
    bindSearch('main-search',()=>{cardLimit=28;renderCards();});
    ['hero-role','hero-sort'].forEach(id=>$(id).addEventListener('change',()=>{heroLimit=28;renderHeroes();}));
    ['rarity','show-deleted'].forEach(id=>$(id).addEventListener('change',()=>{cardLimit=28;renderCards();}));
    $('clear-hero').onclick=()=>{hero='';renderHeroes();renderCards();document.dispatchEvent(new CustomEvent('vga:hero-changed'));};
    $('more-heroes').onclick=()=>{heroLimit+=28;renderHeroes();};
    $('more-cards').onclick=()=>{cardLimit+=28;renderCards();};
    $('favorite-only').onclick=()=>{favoriteOnly=!favoriteOnly;$('favorite-only').setAttribute('aria-pressed',favoriteOnly);cardLimit=28;renderCards();};
    $('close-detail').onclick=closeDialog;
    $('detail').addEventListener('cancel',()=>{detailGeneration++;});
    $('detail').addEventListener('click',event=>{if(event.target===$('detail')){const r=$('detail').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeDialog();}});
    $('about').onclick=showAbout;
    document.addEventListener('click',event=>{
      const button=event.target.closest('button'); if(!button)return;
      if(button.dataset.hero){hero=button.dataset.hero;renderHeroes();renderCards();document.dispatchEvent(new CustomEvent('vga:hero-changed'));}
      else if(button.dataset.favorite)saveFavorite(button.dataset.favorite,button.dataset.name);
      else if(button.dataset.detailKind)openDetail(button.dataset.detailKind,button.dataset.name);
      else if(button.dataset.tab){tab=button.dataset.tab;cardLimit=28;$('main-search').value='';updateTab();}
    });
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('detail').open&&document.activeElement?.tagName==='INPUT'){document.activeElement.value='';document.activeElement.dispatchEvent(new Event('input'));heroLimit=28;cardLimit=28;renderHeroes();renderCards();}});
    $('hero-role').hidden=!Object.values(data.heroes).some(item=>item.position.length);
    renderHeroes(); renderCards();
    document.dispatchEvent(new CustomEvent('vga:data-ready'));
  } catch (_) {
    $('source-banner').textContent='本地数据读取失败。请检查服务器终端输出和 README 中的启动步骤。';
    $('cards').innerHTML='<p class="broken">无法读取数据，请刷新或重新启动服务器。</p>';
  }
}
init();
