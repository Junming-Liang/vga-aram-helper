/* Development-only logic checks. A DOM stub is NOT browser/layout validation. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname,'..');
const fixture = JSON.parse(fs.readFileSync(path.join(root,'fixtures/demo.json'),'utf8'));
const source = fs.readFileSync(path.join(root,'static/app.js'),'utf8').replace(/\ninit\(\);\s*$/, '\n');
const elements = new Map();
function el(id) {
  if (!elements.has(id)) elements.set(id,{value:'',checked:false,hidden:false,open:false,innerHTML:'',textContent:'',listeners:{},attributes:{},addEventListener(n,fn){this.listeners[n]=fn;},setAttribute(k,v){this.attributes[k]=v;},showModal(){this.open=true;},close(){this.open=false;},scrollTop:0});
  return elements.get(id);
}
const storage = new Map();
storage.set('hex-reference-original:favorites:v1','{broken JSON');
const context=vm.createContext({console,Intl,Set,JSON,String,Number,encodeURIComponent,document:{getElementById:el,querySelectorAll:()=>[]},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},fetch:async()=>({ok:true,json:async()=>({recommendations:[],warnings:[],missingItems:[]})})});
vm.runInContext(source,context);
// Use the canonical normalized payload, created before this development check.
const normalized=JSON.parse(fs.readFileSync(path.join(root,'reports/demo-normalized-test-input.json'),'utf8'));
context.inputData=normalized;vm.runInContext('data = inputData',context);
let count=0;function check(name,fn){fn();count++;console.log('PASS '+name);}
check('Malformed favorites fall back safely',()=>assert.equal(vm.runInContext('favorites.size',context),0));
check('Text escaping prevents raw HTML markup',()=>assert.equal(vm.runInContext("escapeText('<script>x</script>')",context),'&lt;script&gt;x&lt;/script&gt;'));
check('Missing rate is not replaced with zero',()=>assert.equal(vm.runInContext('rate(null)',context),'暂无数据'));
check('Search normalizes whitespace and case',()=>assert.equal(vm.runInContext("normalized(' A B C ')",context),'abc'));
check('Hero aliases filter',()=>{el('hero-search').value='小星';vm.runInContext('renderHeroes()',context);assert.match(el('heroes').innerHTML,/星火术士/);assert.doesNotMatch(el('heroes').innerHTML,/磐石守卫/);});
check('Support includes both soft and hard support',()=>{el('hero-search').value='';el('hero-role').value='辅助';vm.runInContext('renderHeroes()',context);assert.match(el('heroes').innerHTML,/磐石守卫/);assert.match(el('heroes').innerHTML,/萤光使者/);});
check('Deleted augments hidden by default',()=>assert.equal(vm.runInContext('getMainList().length',context),3));
check('Deleted augment opt-in',()=>{el('show-deleted').checked=true;assert.equal(vm.runInContext('getMainList().length',context),4);el('show-deleted').checked=false;});
check('Rarity filter',()=>{el('rarity').value='gold';assert.equal(vm.runInContext('getMainList()[0].name',context),'晶盾回路（演示）');el('rarity').value='';});
check('Augment description search',()=>{el('main-search').value='连续施放';assert.equal(vm.runInContext('getMainList().length',context),1);el('main-search').value='';});
check('Favorites round-trip and repeat toggle',()=>{vm.runInContext("saveFavorite('augments','星火共鸣（演示）')",context);assert.deepEqual(JSON.parse(storage.get('hex-reference-original:favorites:v1')),['augments:星火共鸣（演示）']);vm.runInContext("favoriteOnly=true",context);assert.equal(vm.runInContext('getMainList().length',context),1);vm.runInContext("saveFavorite('augments','星火共鸣（演示）')",context);assert.equal(vm.runInContext('getMainList().length',context),0);vm.runInContext('favoriteOnly=false',context);});
check('IME input waits for composition end',()=>{context.calls=0;vm.runInContext("bindSearch('test-input',()=>{calls++})",context);el('test-input').listeners.compositionstart();el('test-input').listeners.input();assert.equal(context.calls,0);el('test-input').listeners.compositionend();assert.equal(context.calls,1);});
check('Hero relation badges include trap',()=>{vm.runInContext("hero='星火术士（演示）'",context);assert.match(vm.runInContext("badges('晶盾回路（演示）')",context),/英雄陷阱/);});
check('Item aliases search',()=>{vm.runInContext("tab='items'",context);el('main-search').value='星杖';assert.equal(vm.runInContext('getMainList().length',context),1);el('main-search').value='';});
check('Chinese name tie-break uses Intl.Collator',()=>assert.equal(vm.runInContext("[{name:'中国',winRate:50},{name:'阿狸',winRate:50}].sort(rateSort)[0].name",context),'阿狸'));
(async()=>{
  await vm.runInContext("openDetail('heroes','星火术士（演示）')",context);
  check('Hero detail distinguishes hero pairs from global rates',()=>assert.match(el('detail-content').innerHTML,/全局胜率与英雄配对胜率分开显示/));
  let resolvePending;
  context.fetch=()=>new Promise(resolve=>{resolvePending=resolve;});
  const pending=vm.runInContext("openDetail('augments','星火共鸣（演示）')",context);
  await vm.runInContext("openDetail('items','山峦之心（演示）')",context);
  const before=el('detail-content').innerHTML;
  resolvePending({ok:true,json:async()=>({recommendations:[],warnings:[],missingItems:[]})});await pending;
  check('Stale recommendation response cannot replace newer detail',()=>assert.equal(el('detail-content').innerHTML,before));
  vm.runInContext('closeDialog()',context);
  check('Dialog closure increments generation and closes',()=>assert.equal(el('detail').open,false));
  console.log(`\n${count} JavaScript logic checks passed. DOM stub only; not browser/layout validation.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
