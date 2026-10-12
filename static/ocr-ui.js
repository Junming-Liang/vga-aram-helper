'use strict';
// Optional image processing stays on the user's localhost server.
(async function initScreenshotOCR(){
  const fileInput=document.getElementById('ocr-file');
  const run=document.getElementById('ocr-run');
  const status=document.getElementById('ocr-status');
  const results=document.getElementById('ocr-results');
  let enabled=false, generation=0;
  try{
    const response=await fetch('/health');
    const health=await response.json();enabled=health.ocr_enabled===true;
    fileInput.disabled=!enabled;
    status.textContent=enabled?'已启用本地 OCR。仅识别名称，不识别英雄、不读取游戏进程。':'尚未启用。按 README 安装可选 OCR 依赖，然后用 --enable-ocr 启动。普通查阅仍可使用。';
  }catch(_){status.textContent='无法读取 OCR 状态，请确认本地服务器仍在运行。';}
  document.addEventListener('vga:round-cleared',()=>{generation++;results.textContent='';status.textContent='新一轮：请重新选择截图或手动输入三个候选。';fileInput.disabled=!enabled;run.disabled=!enabled||!fileInput.files.length;});
  fileInput.addEventListener('change',()=>{generation++;window.VGAChoices.clear();results.textContent='';run.disabled=!enabled||!fileInput.files.length;});
  run.addEventListener('click',async()=>{
    const file=fileInput.files[0];if(!file)return;
    const current=++generation;
    if(file.size>8*1024*1024){status.textContent='图片不能超过 8 MiB。';return;}
    run.disabled=true;fileInput.disabled=true;results.textContent='';
    status.textContent='正在本机识别…首次加载模型可能较慢。';
    try{
      const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
      const response=await fetch('/api/ocr',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:base64})});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'识别失败');
      if(current!==generation)return;
      status.textContent=`识别到 ${result.candidates.length} 个词典候选。请核对后加入三个选项；OCR 置信度不是胜率。`;
      if(result.candidates.length===3){const fill=document.createElement('button');fill.textContent='确认这三个名称，填入候选';fill.className='primary-button';fill.addEventListener('click',()=>{window.VGAChoices.fillOffered(result.candidates.map(x=>x.name));status.textContent='已填入三个名称。请核对位置和所选英雄，再点击比较。';});results.appendChild(fill);}

      if(!result.candidates.length){results.textContent='没有足够可靠的词典匹配。可裁剪到卡片标题后重试，或手动搜索。演示模式词典只含虚构海克斯。';return;}
      for(const item of result.candidates){
        const button=document.createElement('button');button.className='ocr-candidate';
        const label=document.createElement('strong');label.textContent=`加入空位：${item.name}`;
        const detail=document.createElement('small');detail.textContent=`OCR置信度 ${(item.ocr_confidence*100).toFixed(1)}% · 名称相似度 ${(item.name_similarity*100).toFixed(1)}%${item.match_method==='fuzzy-suggestion'?' · 模糊候选':''}`;
        button.append(label,detail);button.addEventListener('click',()=>{window.VGAChoices.addCandidate(item.name);});results.appendChild(button);
      }
    }catch(error){status.textContent=String(error.message||'本地 OCR 出错，请重试。');}
    finally{if(current===generation){fileInput.disabled=!enabled;run.disabled=!enabled||!fileInput.files.length;}}
  });
})();
