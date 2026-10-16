/* Development-only VM/DOM-stub regression checks, not rendered-browser QA. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..'),elements=new Map(),events=new Map();
function el(id){if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',textContent:'',disabled:false,hidden:false,listeners:{},addEventListener(type,fn){this.listeners[type]=fn;},focus(){},setAttribute(){}});return elements.get(id);}
const doc={getElementById:el,addEventListener(type,fn){events.set(type,fn);},dispatchEvent(event){events.get(event.type)?.(event);}};
let pending=[];
const ctx=vm.createContext({console,document:doc,window:{confirm:()=>false},Intl,Set,JSON,String,Number,AbortController,CustomEvent:class{constructor(type){this.type=type;}},setTimeout:()=>0,
 $:el,escapeText:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
 collator:new Intl.Collator('zh-CN'),rate:v=>typeof v==='number'?v.toFixed(2)+'%':'暂无数据',
 data:{metadata:{isDemo:true},heroes:{甲:{},乙:{}},augments:{甲卡:{},乙卡:{},丙卡:{}}},hero:'',
 fetch:(url,opts)=>url==='/api/status'?Promise.resolve({ok:true,json:async()=>({data:{state:'demo'},software:{state:'disabled'},applicationVersion:'test'})}):new Promise(resolve=>pending.push({resolve,body:JSON.parse(opts.body),signal:opts.signal}))});
vm.runInContext(fs.readFileSync(path.join(root,'static/choices.js'),'utf8'),ctx);
let count=0;function check(name,fn){fn();count++;console.log('PASS '+name);}
function click(id){return el(id).listeners.click();}
function input(i,value){el('choice-'+i).value=value;el('choice-'+i).listeners.input();}
function emit(type){doc.dispatchEvent({type});}
function response(name='甲卡') {return {policy:'official-hero-source-order-v1',decision:name+'优先',policyExplanation:'源顺位',recommendedName:name,cards:[{name,slot:1,officialRank:1,officialStats:{},tier:'T1',sourceTier:'T1',pairWinRate:55,pickRate:8,numGames:100,category:'unknown',positiveEvidence:[],trapEvidence:[],conditionFlags:[],cautionFlags:[],matchingTags:[],globalReferenceWinRate:null,globalRateNote:'全局不用于排序'}],warnings:[]};}
(async()=>{
 check('No hero cannot compare',()=>assert.equal(el('compare-choices').disabled,true));
 ctx.hero='甲';emit('vga:hero-changed');ctx.window.VGAChoices.fillOffered(['甲卡','乙卡','丙卡']);
 check('Three valid reviewed names enable explicit confirm',()=>assert.equal(el('compare-choices').disabled,false));
 check('OCR fill never sends comparison automatically',()=>assert.equal(pending.length,0));
 input(2,'乙卡');check('Duplicate slots are blocked',()=>assert.equal(el('compare-choices').disabled,true));
 input(2,'未知');check('Unrecognized names are blocked',()=>assert.equal(el('compare-choices').disabled,true));
 input(2,'');check('Incomplete slots are blocked',()=>assert.equal(el('compare-choices').disabled,true));
 input(2,'丙卡');const first=click('compare-choices');check('Post preserves hero and all three confirmed slots',()=>assert.deepEqual(pending[0].body,{hero:'甲',offered:['甲卡','乙卡','丙卡']}));
 input(0,'丙卡');check('Edit aborts and invalidates pending comparison',()=>assert.equal(pending[0].signal.aborted,true));
 pending[0].resolve({ok:true,json:async()=>response('旧结果')});await first;
 check('Old response cannot appear after manual edit',()=>assert.equal(el('choice-result').innerHTML,''));
 ctx.window.VGAChoices.fillOffered(['甲卡','乙卡','丙卡']);const second=click('compare-choices');ctx.hero='乙';emit('vga:hero-changed');pending[1].resolve({ok:true,json:async()=>response('旧英雄')});await second;
 check('Hero switch invalidates stale recommendation',()=>assert.equal(el('choice-result').innerHTML,''));
 const third=click('compare-choices');pending[2].resolve({ok:true,json:async()=>response('<script>坏值</script>')});await third;
 check('Source candidate text is escaped in results',()=>{assert.match(el('choice-result').innerHTML,/&lt;script&gt;/);assert.doesNotMatch(el('choice-result').innerHTML,/<script>/);});
 check('Only literal grade renders even with legacy rate payload',()=>{assert.match(el('choice-result').innerHTML,/源评级 T1/);assert.doesNotMatch(el('choice-result').innerHTML,/胜率|选取率|样本量|55\.00|源顺位|优先考虑/);});
 click('clear-choices');check('Reroll clears all slots and results',()=>{assert.equal(el('choice-0').value,'');assert.equal(el('choice-result').innerHTML,'');assert.equal(el('compare-choices').disabled,true);});
 ctx.window.VGAChoices.addCandidate('甲卡');check('Partial OCR selection fills only an empty slot',()=>{assert.equal(el('choice-0').value,'甲卡');assert.equal(el('choice-1').value,'');});
 ctx.window.VGAChoices.addCandidate('甲卡');check('Repeated OCR candidate is not duplicated',()=>assert.equal(el('choice-1').value,''));
 check('OCR cannot auto-fill ambiguous list lengths',()=>assert.equal(ctx.window.VGAChoices.fillOffered(['甲卡','乙卡']),false));
 console.log(`\n${count} three-choice UI logic checks passed. DOM stub only.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
